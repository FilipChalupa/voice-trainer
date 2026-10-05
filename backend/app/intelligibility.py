"""Can the trained voice be understood? It reads a fixed set of sentences and Whisper writes down what it hears.

The estimated MOS of a run says how natural the voice sounds, not whether the words come out right. Here the
transcript is compared with the text (both in their spoken form: numbers in words, loanwords respelled), which
gives one number to compare runs by and the list of sentences and words the voice garbles. The untouched base
voice reads the same sentences once, as the yardstick: Whisper does not score 100 % on a perfect voice either.
"""
from __future__ import annotations

import difflib
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .config import BASE_DIR, LANGUAGES, Voice, load_settings, now, pronounce
from .runs import SAFE, find_job_dir, list_exports, read_json

router = APIRouter(prefix="/api", tags=["intelligibility"])

UNDERSTOOD = 0.9  # a sentence below this similarity counts as garbled
TIMEOUT_SECONDS = 600

# plain sentences, questions, loanwords, numbers and units, hard "ti di ni", consonant clusters, rare sounds, names
SENTENCES: dict[str, list[str]] = {
    "cs": [
        "Dobrý den, tohle je zkouška mého nového hlasu.",
        "V obývacím pokoji svítí lampa a okno je zavřené.",
        "Pračka doprala, nezapomeňte pověsit prádlo.",
        "Zítra bude převážně oblačno, odpoledne místy přeháňky.",
        "Mám pustit rádio, nebo chcete raději ticho?",
        "Kdy přijede kurýr s balíkem?",
        "Opravdu jste zamkli garáž?",
        "Přišel vám nový e-mail a dvě zprávy.",
        "Software se aktualizuje přes noc.",
        "K snídani si dám croissant a pomerančový džus.",
        "V sobotu jdeme na jazzový koncert.",
        "Venku je 23,5 °C a vlhkost 45 %.",
        "Schůzka začíná ve 14:30 a končí v 16:00.",
        "Spotřeba za dnešek je 5 kWh.",
        "Účet za elektřinu je 1 250 Kč.",
        "Martin má tip na dobrý festival.",
        "Technik opravil tiskárnu během chvilky.",
        "Čtvrtek je čtvrtý den v týdnu.",
        "Vlk zmrzl, zhltl hrst zrn.",
        "Džbán s džusem stojí na stole vedle džemu.",
        "Autobus zastavil u sauny na pauzu.",
        "Z Liberce jedeme přes Hradec Králové do Pardubic.",
        "Kateřina Kučerová poslala zprávu.",
        "Kotel v technické místnosti hlásí poruchu.",
    ],
    "en": [
        "Hello, this is a test of my new voice.",
        "The lamp in the living room is on and the window is closed.",
        "The washing machine has finished, do not forget the laundry.",
        "Tomorrow will be mostly cloudy with showers in the afternoon.",
        "Should I turn on the radio, or would you prefer silence?",
        "When will the courier arrive with the parcel?",
        "Did you really lock the garage?",
        "You have a new email and two messages.",
        "The colonel walked his dog along the quay.",
        "She bought a thorough guide to the borough.",
        "It is twenty three degrees outside and the humidity is forty five percent.",
        "The meeting starts at half past two and ends at four.",
    ],
}


def missed_words(expected: str, heard: str, language: str) -> list[str]:
    """Words of the text Whisper did not hear the way they are said."""
    from trainer.verify_worker import normalize

    a, b = normalize(expected, language), normalize(heard, language)
    out: list[str] = []
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            out.extend(a[i1:i2])
    return out


def summarize(items: list[dict[str, Any]], language: str) -> dict[str, Any]:
    from trainer.verify_worker import normalize

    words = sum(len(normalize(i["text"], language)) for i in items)
    missed = sum(len(i["missed"]) for i in items)
    return {
        "score": round(100 * sum(i["similarity"] for i in items) / max(1, len(items)), 1),
        "word_accuracy": round(100 * (1 - missed / max(1, words)), 1),
        "garbled": sum(1 for i in items if i["similarity"] < UNDERSTOOD),
        "count": len(items),
    }


class Tester:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"status": "idle", "job_id": None, "progress": None, "error": None}

    def is_running(self) -> bool:
        return self.state["status"] == "running"

    def snapshot(self, job_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = dict(self.state)
        if job_id:
            state["result"] = read_json(find_job_dir(job_id) / "intelligibility" / "result.json") or None
            if state["job_id"] != job_id:
                state = {**state, "status": "idle" if state["result"] is None else "done", "progress": None, "error": None}
        return state

    def start(self, job_id: str, file: str | None = None) -> dict[str, Any]:
        from .jobs import manager

        if self.is_running():
            raise HTTPException(409, {"code": "check_running", "message": "A test is already running"})
        if manager.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is running; Whisper needs the GPU too"})
        job_dir = find_job_dir(job_id)
        job = read_json(job_dir / "job.json")
        exports = list_exports(job_dir, job_id)
        if not exports:
            raise HTTPException(409, {"code": "no_models", "message": "This run has no exported voice yet"})
        preferred = "best_mel" if read_json(job_dir / "result.json").get("stopped_early") else "last"
        export = next((e for e in exports if e["file"] == file), None) or next((e for e in exports if e["variant"] == preferred), exports[0])
        with self._lock:
            self.state = {"status": "running", "job_id": job_id, "progress": {"current": 0, "total": 0}, "error": None}
        threading.Thread(target=self._run, args=(job_dir, job, export), daemon=True).start()
        return self.snapshot(job_id)

    def _read(self, model_path: Path, out_dir: Path, sentences: list[str], lexicon: dict[str, str], language: str, offset: int, total: int) -> list[dict[str, Any]]:
        """One voice reads the sentences, Whisper transcribes them; returns a row per sentence."""
        from .synth import synthesize
        from .verify import verifier

        out_dir.mkdir(parents=True, exist_ok=True)
        whisper_language = LANGUAGES[language]["espeak"].split("-")[0]
        answers: dict[int, dict[str, Any]] = {}
        done = threading.Event()

        def collect(i: int, ev: dict[str, Any]) -> None:
            answers[i] = ev
            with self._lock:
                self.state["progress"] = {"current": offset + len(answers), "total": total}
            if len(answers) == len(sentences):
                done.set()

        for i, text in enumerate(sentences):
            path = out_dir / f"{i:02d}.wav"
            path.write_bytes(synthesize(model_path, pronounce(text, lexicon, language), 1.0, 0.667, 0.8))
            verifier.request(f"intelligibility-{out_dir.parent.name}-{out_dir.name}-{i}", path, text, whisper_language, lambda ev, i=i: collect(i, ev))
        if not done.wait(TIMEOUT_SECONDS):
            raise RuntimeError("Whisper did not answer in time")
        rows = []
        for i, text in enumerate(sentences):
            ev = answers[i]
            if ev.get("event") != "result":
                raise RuntimeError(str(ev.get("message") or "Whisper failed"))
            heard = str(ev.get("transcript", ""))
            rows.append({"index": i, "text": text, "heard": heard, "similarity": float(ev.get("similarity") or 0.0), "missed": missed_words(text, heard, whisper_language)})
        return rows

    def _run(self, job_dir: Path, job: dict[str, Any], export: dict[str, Any]) -> None:
        from .base import ensure_base_voice

        try:
            settings = load_settings(Voice(job["voice_id"]))
            language, lexicon = settings["language"], settings.get("lexicon") or {}
            whisper_language = LANGUAGES[language]["espeak"].split("-")[0]
            sentences = SENTENCES.get(language) or SENTENCES["en"]
            baseline_file = BASE_DIR / "intelligibility" / language / "result.json"
            baseline = read_json(baseline_file) or None
            if baseline and baseline.get("sentences") != sentences:
                baseline = None
            total = len(sentences) * (1 if baseline else 2)
            with self._lock:
                self.state["progress"] = {"current": 0, "total": total}
            out_dir = job_dir / "intelligibility"
            rows = self._read(job_dir / "export" / export["file"], out_dir / "audio", sentences, lexicon, language, 0, total)
            if baseline is None:
                # the yardstick; without the base voice at hand the test still gives its own numbers
                try:
                    base_rows = self._read(ensure_base_voice(language), baseline_file.parent / "audio", sentences, {}, language, len(sentences), total)
                    baseline = {**summarize(base_rows, whisper_language), "sentences": sentences, "created_at": now()}
                    baseline_file.write_text(json.dumps(baseline, ensure_ascii=False, indent=1))
                except Exception:  # noqa: BLE001
                    baseline = None
            rows.sort(key=lambda r: r["similarity"])
            result = {
                "job_id": job_dir.name,
                "variant": export["variant"],
                "file": export["file"],
                "created_at": now(),
                **summarize(rows, whisper_language),
                "baseline": {k: baseline[k] for k in ("score", "word_accuracy", "garbled")} if baseline else None,
                "items": rows,
            }
            (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
            with self._lock:
                self.state.update(status="done")
        except HTTPException as exc:
            with self._lock:
                self.state.update(status="failed", error=str((exc.detail or {}).get("message") if isinstance(exc.detail, dict) else exc.detail))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.state.update(status="failed", error=str(exc))


tester = Tester()


@router.post("/jobs/{job_id}/intelligibility")
def post_intelligibility(job_id: str, body: dict[str, Any] | None = None):
    return tester.start(job_id, str((body or {}).get("file") or "") or None)


@router.get("/jobs/{job_id}/intelligibility")
def get_intelligibility(job_id: str):
    return tester.snapshot(job_id)


@router.get("/jobs/{job_id}/intelligibility/audio/{index}")
def get_intelligibility_audio(job_id: str, index: str):
    if not SAFE.match(index or "") or not index.isdigit():
        raise HTTPException(400, {"code": "bad_id", "message": "Bad sentence number"})
    path = find_job_dir(job_id) / "intelligibility" / "audio" / f"{int(index):02d}.wav"
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "No reading of this sentence"})
    return FileResponse(path, media_type="audio/wav")
