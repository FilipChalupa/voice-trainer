"""Import of a long recording: Whisper transcribes it, the sentences become individual recordings."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .config import BASE_DIR, LANGUAGES, Voice, load_settings
from .events import parse_event, progress_percent, pump
from .recordings import list_recordings, store_recording, total_minutes
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["import"])

BACKEND_ROOT = Path(__file__).resolve().parent.parent
WHISPER_DIR = BASE_DIR / "whisper"
WHISPER_MODEL = os.environ.get("VT_WHISPER_MODEL", "turbo")
WHISPER_LANGUAGE = {"cs": "cs", "en": "en"}
MAX_UPLOAD = 2 << 30  # 2 GB
RUNNING = ("uploading", "downloading", "loading", "transcribing", "cutting", "storing")


def transcribe_command(source: Path, work: Path, language: str) -> list[str]:
    return [sys.executable, "-m", "trainer.transcribe", "--input", str(source), "--out-dir", str(work), "--language", language, "--model", WHISPER_MODEL, "--download-root", str(WHISPER_DIR)]


class Transcriber:
    """One transcription at a time; the state is polled by the UI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self.state: dict[str, Any] = self._idle()

    @staticmethod
    def _idle() -> dict[str, Any]:
        return {"status": "idle", "voice_id": None, "file": None, "progress": None, "device": None, "model": WHISPER_MODEL, "model_installed": any(WHISPER_DIR.glob("*.pt")), "result": None, "error": None, "log": []}

    def is_running(self) -> bool:
        return self.state["status"] in RUNNING

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self.state.update(fields)

    def _log(self, line: str) -> None:
        line = line.rstrip()
        if line:
            with self._lock:
                self.state["log"] = (self.state["log"] + [line])[-40:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.state)

    def start(self, voice: Voice, source: Path, original_name: str) -> dict[str, Any]:
        from .jobs import manager

        if self.is_running():
            raise HTTPException(409, {"code": "import_running", "message": "Another recording is being transcribed"})
        if manager.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is running; transcribe afterwards (both need the GPU)"})
        from .verify import verifier

        verifier.stop()
        settings = load_settings(voice)
        with self._lock:
            self.state = {**self._idle(), "status": "loading", "voice_id": voice.id, "file": original_name}
        self._cancel.clear()
        threading.Thread(target=self._run, args=(voice, source, WHISPER_LANGUAGE.get(settings["language"], "en")), daemon=True).start()
        return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        if not self.is_running():
            raise HTTPException(409, {"code": "not_running", "message": "Nothing is being transcribed"})
        self._cancel.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
        return self.snapshot()

    def _run(self, voice: Voice, source: Path, language: str) -> None:
        work = source.parent
        try:
            cmd = transcribe_command(source, work, language)
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(BACKEND_ROOT), "NUMBA_CACHE_DIR": os.environ.get("NUMBA_CACHE_DIR", "/tmp/numba_cache")}
            WHISPER_DIR.mkdir(parents=True, exist_ok=True)
            self._proc = subprocess.Popen(cmd, cwd=str(work), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
            pump(self._proc, self._handle_line)
            code = self._proc.wait()
            if self._cancel.is_set():
                self._update(status="cancelled")
                return
            if code != 0:
                raise RuntimeError(self.state.get("error") or f"Transcription exited with code {code}")
            clips = json.loads((work / "clips.json").read_text())
            self._update(status="storing", progress={"current": 0, "total": len(clips)})
            stored, skipped = 0, 0
            for i, clip in enumerate(clips):
                if self._cancel.is_set():
                    self._update(status="cancelled")
                    return
                try:
                    store_recording(voice, (work / "clips" / clip["file"]).read_bytes(), clip["text"], source="transcribed")
                    stored += 1
                except HTTPException:
                    skipped += 1
                self._update(progress={"current": i + 1, "total": len(clips)})
            items = list_recordings(voice)
            self._update(status="done", result={"stored": stored, "skipped": skipped, "count": len(items), "minutes": round(total_minutes(items), 2)}, model_installed=True)
        except Exception as exc:  # noqa: BLE001
            self._log(f"ERROR: {exc}")
            self._update(status="failed", error=str(exc))
        finally:
            self._proc = None
            shutil.rmtree(work, ignore_errors=True)
            try:
                work.parent.rmdir()  # the imports folder is only needed while something is being transcribed
            except OSError:
                pass

    def _handle_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        percent = progress_percent(line)
        if percent is not None:
            # tqdm of the model download and of the transcription itself
            self._update(progress={"current": percent, "total": 100})
            return
        ev = parse_event(line)
        if ev is None:
            self._log(line)
            return
        kind = ev.get("event")
        if kind == "stage":
            self._update(status=ev.get("stage"), progress=None, device=ev.get("device", self.state.get("device")))
            self._log(f"{ev.get('stage')}: {json.dumps({k: v for k, v in ev.items() if k not in ('event', 'stage')}, ensure_ascii=False)}")
        elif kind == "done":
            self._log(f"{ev.get('clips')} sentences found in {ev.get('seconds')} s of audio")
        elif kind == "log":
            self._log(str(ev.get("message", "")))
        elif kind == "error":
            self._update(error=str(ev.get("message")))
            self._log(f"ERROR: {ev.get('message')}")


transcriber = Transcriber()


@router.post("/transcribe")
async def post_transcribe(file: UploadFile = File(...), hints: str = Form("")):
    """Uploads a long recording; it is transcribed and cut into sentences in the background."""
    voice = require_voice()
    if transcriber.is_running():
        raise HTTPException(409, {"code": "import_running", "message": "Another recording is being transcribed"})
    if load_settings(voice)["language"] not in LANGUAGES:
        raise HTTPException(400, {"code": "bad_language", "message": "Unsupported language"})
    suffix = Path(file.filename or "audio").suffix.lower() or ".bin"
    if suffix not in (".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".aac", ".webm", ".mp4", ".wma"):
        raise HTTPException(400, {"code": "bad_audio", "message": "Unsupported file type"})
    work = voice.dir / "imports" / time.strftime("%Y%m%d_%H%M%S")
    work.mkdir(parents=True, exist_ok=True)
    source = work / f"source{suffix}"
    size = 0
    with source.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                shutil.rmtree(work, ignore_errors=True)
                raise HTTPException(413, {"code": "too_large", "message": "The file is larger than 2 GB"})
            out.write(chunk)
    if size == 0:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(400, {"code": "empty_upload", "message": "Empty upload"})
    try:
        # the glossary handed to Whisper: what the person typed plus the words of the pronunciation list
        terms = [hints.strip(), *(load_settings(voice).get("lexicon") or {}).keys()]
        glossary = ", ".join(t for t in terms if t)
        if glossary:
            (work / "hints.txt").write_text(glossary[:800], encoding="utf-8")
        return transcriber.start(voice, source, file.filename or source.name)
    except HTTPException:
        shutil.rmtree(work, ignore_errors=True)
        raise


@router.get("/transcribe")
def get_transcribe():
    return transcriber.snapshot()


@router.post("/transcribe/cancel")
def cancel_transcribe():
    return transcriber.cancel()
