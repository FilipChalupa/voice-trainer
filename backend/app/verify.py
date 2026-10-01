"""Checks a take against its sentence with Whisper: did the person read what is written?

Used by the flow reading mode, where takes are cut automatically and may end up with the wrong sentence.
One worker process keeps the model loaded and exits after a while without requests; it stays off while
training runs (both want the GPU)."""
from __future__ import annotations

import json
import os
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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"running": self.running(), "ready": self._ready, "pending": len(self._pending), "error": self.error}


verifier = Verifier()


@router.post("/recordings/{rid}/verify")
def post_verify(rid: str):
    if not SAFE_ID.match(rid or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad recording id"})
    return verifier.submit(require_voice(), rid)


@router.get("/verify")
def get_verify():
    return verifier.snapshot()
