"""Checks a take against its sentence with Whisper: did the person read what is written?

Used by the flow reading mode, where takes are cut automatically and may end up with the wrong sentence.
One worker process keeps the model loaded and exits after a while without requests; it stays off while
training runs (both want the GPU)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .config import BASE_DIR, LANGUAGES, Voice, load_settings
from .recordings import SAFE_ID, load_index, save_index
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["verify"])

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MATCH_THRESHOLD = 0.8  # word-level similarity below which the take is marked as not matching its sentence
IDLE_SECONDS = 600


def worker_command() -> list[str]:
    return [sys.executable, "-m", "trainer.verify_worker"]


class Verifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._ready = False
        self._pending: dict[str, dict[str, Any]] = {}
        self._last_used = 0.0
        self.error: str | None = None
        threading.Thread(target=self._idle_watch, daemon=True).start()

    # ----- worker lifecycle -----
    def _start(self) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(BACKEND_ROOT), "VT_WHISPER_DIR": str(BASE_DIR / "whisper")}
        (BASE_DIR / "whisper").mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True, bufsize=1)
        self._ready = False
        self.error = None
        threading.Thread(target=self._reader, args=(self._proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "ready":
                self._ready = True
            elif ev.get("event") in ("result", "error"):
                with self._lock:
                    task = self._pending.pop(str(ev.get("id")), None)
                if task:
                    self._store(task, ev)
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._ready = False
                for task in self._pending.values():
                    self._store(task, {"event": "error", "message": "worker exited"})
                self._pending.clear()

    def _idle_watch(self) -> None:
        while True:
            time.sleep(30)
            with self._lock:
                proc = self._proc
                idle = proc is not None and not self._pending and time.time() - self._last_used > IDLE_SECONDS
            if idle and proc is not None:
                self.stop()

    def stop(self) -> None:
        with self._lock:
            proc, self._proc, self._ready = self._proc, None, False
        if proc and proc.poll() is None:
            proc.terminate()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ----- requests -----
    def submit(self, voice: Voice, rid: str) -> dict[str, Any]:
        from .jobs import manager

        if manager.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is running; verification needs the GPU too"})
        index = load_index(voice)
        if rid not in index:
            raise HTTPException(404, {"code": "not_found", "message": "Recording not found"})
        settings = load_settings(voice)
        task = {"id": rid, "voice_id": voice.id, "path": str(voice.recordings_dir / f"{rid}.wav"), "text": index[rid]["text"], "language": LANGUAGES[settings["language"]]["espeak"].split("-")[0]}
        with self._lock:
            if not self.running():
                self._start()
            self._pending[rid] = task
            self._last_used = time.time()
            index[rid]["verify"] = {"status": "pending"}
            save_index(voice, index)
            assert self._proc and self._proc.stdin
            self._proc.stdin.write(json.dumps({k: task[k] for k in ("id", "path", "text", "language")}, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        return {"status": "pending"}

    def _store(self, task: dict[str, Any], ev: dict[str, Any]) -> None:
        voice = Voice(task["voice_id"])
        with self._lock:
            index = load_index(voice)
            entry = index.get(task["id"])
            if entry is None:
                return
            if ev.get("event") == "result":
                sim = float(ev.get("similarity") or 0.0)
                entry["verify"] = {"status": "ok" if sim >= MATCH_THRESHOLD else "mismatch", "transcript": ev.get("transcript", ""), "similarity": sim}
            else:
                entry["verify"] = {"status": "error", "message": str(ev.get("message"))}
            save_index(voice, index)
        if ev.get("event") == "result":
            try:
                reconcile(voice, task["id"])
            except Exception:  # noqa: BLE001  (a failed repair leaves the plain verdicts in place)
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"running": self.running(), "ready": self._ready, "pending": len(self._pending), "error": self.error}


WINDOW_BEFORE, WINDOW_AFTER = 2, 3


def reconcile(voice: Voice, rid: str) -> None:
    """Repairs the bookkeeping of flow-mode takes around ``rid`` once Whisper has heard them.

    The reader skipped a sentence: the take matches a neighbouring sentence better, so it is relabelled and the
    sentence left without a take comes up again by itself. The reader paused inside a sentence: two
    consecutive takes together match one sentence, so they are joined into one. Duplicates of a sentence keep
    the take Whisper agrees with most.
    """
    import numpy as np
    import soundfile as sf

    from .recordings import _to_trash
    from .prompts import prompt_id
    from trainer.verify_worker import similarity as _similarity

    lang = LANGUAGES[load_settings(voice)["language"]]["espeak"].split("-")[0]

    def similarity(expected: str, heard: str) -> float:
        return _similarity(expected, heard, lang)

    with _reconcile_lock:
        index = load_index(voice)
        order = sorted(index, key=lambda k: index[k].get("created") or "")
        if rid not in order:
            return
        pos = order.index(rid)
        window = order[max(0, pos - WINDOW_BEFORE) : pos + WINDOW_AFTER + 1]
        heard = {k: (index[k].get("verify") or {}) for k in window}
        if any(h.get("status") in (None, "pending") for h in heard.values()):
            return  # wait until the whole neighbourhood is checked
        changed = False

        # 1. two consecutive takes that together read one sentence (a pause inside it)
        for a, b in zip(window, window[1:]):
            if a not in index or b not in index:
                continue
            ha, hb = heard[a], heard[b]
            if ha.get("status") != "mismatch" or hb.get("status") != "mismatch":
                continue
            joined = f"{ha.get('transcript', '')} {hb.get('transcript', '')}"
            if similarity(index[a]["text"], joined) >= MATCH_THRESHOLD:
                pa, pb = voice.recordings_dir / f"{a}.wav", voice.recordings_dir / f"{b}.wav"
                xa, sr = sf.read(str(pa), dtype="float32", always_2d=True)
                xb, _ = sf.read(str(pb), dtype="float32", always_2d=True)
                gap = np.zeros((int(sr * 0.15), 1), dtype=np.float32)
                sf.write(str(pa), np.concatenate([xa, gap, xb]), sr, subtype="PCM_16")
                index[a]["verify"] = {"status": "ok", "transcript": joined, "similarity": similarity(index[a]["text"], joined), "merged": b}
                _to_trash(voice, b)
                index.pop(b, None)
                heard.pop(b, None)
                changed = True
        window = [k for k in window if k in index]

        # 2. a take that reads a neighbouring sentence better than its own
        texts = {k: index[k]["text"] for k in window}
        for k in window:
            h = heard.get(k) or {}
            if h.get("status") != "mismatch":
                continue
            best, best_sim = None, 0.0
            for other, text in texts.items():
                sim = similarity(text, h.get("transcript", ""))
                if sim > best_sim:
                    best, best_sim = other, sim
            if best is not None and best != k and best_sim >= MATCH_THRESHOLD:
                index[k]["text"] = texts[best]
                index[k]["prompt_id"] = index[best].get("prompt_id") or prompt_id(texts[best])
                index[k]["verify"] = {"status": "ok", "transcript": h.get("transcript", ""), "similarity": best_sim, "relabelled": True}
                changed = True

        # 3. two takes of the same sentence: keep the one Whisper agrees with most
        by_text: dict[str, list[str]] = {}
        for k in window:
            by_text.setdefault(index[k]["text"], []).append(k)
        for keys in by_text.values():
            if len(keys) < 2:
                continue
            keys.sort(key=lambda k: float((index[k].get("verify") or {}).get("similarity") or 0.0), reverse=True)
            for loser in keys[1:]:
                _to_trash(voice, loser)
                index.pop(loser, None)
                changed = True

        if changed:
            save_index(voice, index)


_reconcile_lock = threading.Lock()
verifier = Verifier()


@router.post("/recordings/{rid}/verify")
def post_verify(rid: str):
    if not SAFE_ID.match(rid or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad recording id"})
    return verifier.submit(require_voice(), rid)


def lexicon_suggestions(entries: list[dict[str, Any]], lexicon: dict[str, str], language: str = "cs", limit: int = 20) -> list[dict[str, Any]]:
    """Words Whisper keeps hearing differently than they are written and the dictionary does not know: names
    and terms. Those are the words the trained voice is most likely to say oddly too, so they are offered for
    the lexicon with the heard form as a starting point for the respelling. Whisper's own spelling habits
    (mně/mě, tří/tři) are dictionary words and stay out."""
    import difflib
    from collections import Counter, defaultdict

    from trainer.verify_worker import normalize

    from .prompts import _dictionary

    dictionary = _dictionary(language)
    language = LANGUAGES.get(language, LANGUAGES["cs"])["espeak"].split("-")[0]
    known = {w.lower() for w in lexicon}
    heard_as: dict[str, Counter] = defaultdict(Counter)
    takes: Counter = Counter()
    original: dict[str, str] = {}
    for entry in entries:
        transcript = (entry.get("verify") or {}).get("transcript")
        text = entry.get("text") or ""
        if not transcript or not text:
            continue
        a, b = normalize(text, language), normalize(transcript, language)
        for w in set(a):
            takes[w] += 1
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != "replace" or i2 - i1 != j2 - j1:
                continue  # only word-for-word swaps say something about one word
            for w, h in zip(a[i1:i2], b[j1:j2]):
                if len(w) < 3 or w == h or w in known:
                    continue
                if w not in original:
                    m = re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text, flags=re.IGNORECASE)
                    original[w] = m.group(0) if m else w
                if dictionary is not None and (dictionary.lookup(original[w]) or dictionary.lookup(w)):
                    continue
                heard_as[w][h] += 1
    out = []
    for w, counter in heard_as.items():
        heard, n = counter.most_common(1)[0]
        # at least twice, and in at least half of the takes that contain the word: a slip of the tongue once is not a term
        if n >= 2 and n * 2 >= takes[w]:
            out.append({"word": original.get(w, w), "heard": heard, "count": n, "takes": takes[w]})
    out.sort(key=lambda s: (-s["count"], s["word"]))
    return out[:limit]


@router.get("/lexicon/suggestions")
def get_lexicon_suggestions():
    voice = require_voice()
    settings = load_settings(voice)
    return {"items": lexicon_suggestions(list(load_index(voice).values()), settings.get("lexicon") or {}, settings["language"])}


@router.get("/verify")
def get_verify():
    return verifier.snapshot()
