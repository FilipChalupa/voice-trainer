"""Checks the recordings with the trained voice: every training sentence is synthesised and compared to the take.

A sentence the model cannot reproduce (a large mel distance after time alignment) was usually misread, has a
wrong transcript or contains noise. The check runs on the CPU with the exported ONNX voice.
"""
from __future__ import annotations

import json
import statistics
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .config import Voice, load_settings, now, pronounce
from .runs import SAFE, find_job_dir, list_exports, read_json
from .recordings import list_recordings

router = APIRouter(prefix="/api", tags=["check"])

Z_THRESHOLD = 2.0  # recordings this far above the typical distance get the model_mismatch flag
CHECK_FILE = "model_check.json"  # in the voice directory: the latest check, read by the recording list


def mel_distance(reference, synthesized, sample_rate: int) -> float:
    """Average per-frame cosine distance of the log-mel spectrograms along the DTW path."""
    import librosa
    import numpy as np

    def mel(audio):
        m = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_fft=1024, hop_length=256, n_mels=80, fmin=0, fmax=8000)
        return np.log(np.maximum(m, 1e-5))

    x, y = mel(reference), mel(synthesized)
    cost, path = librosa.sequence.dtw(X=x, Y=y, metric="cosine")
    return float(cost[-1, -1] / max(1, len(path)))


class Checker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"status": "idle", "job_id": None, "progress": None, "error": None}

    def is_running(self) -> bool:
        return self.state["status"] == "running"

    def snapshot(self, job_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = dict(self.state)
        if job_id:
            job_dir = find_job_dir(job_id)
            state["result"] = read_json(job_dir / "check" / "result.json") or None
            if state["job_id"] != job_id:
                state = {**state, "status": "idle" if state["result"] is None else "done", "progress": None, "error": None}
        return state

    def start(self, job_id: str) -> dict[str, Any]:
        if self.is_running():
            raise HTTPException(409, {"code": "check_running", "message": "A check is already running"})
        job_dir = find_job_dir(job_id)
        job = read_json(job_dir / "job.json")
        exports = list_exports(job_dir, job_id)
        if not exports:
            raise HTTPException(409, {"code": "no_models", "message": "This run has no exported voice yet"})
        result = read_json(job_dir / "result.json")
        preferred = "best_mel" if result.get("stopped_early") else "last"
        export = next((e for e in exports if e["variant"] == preferred), exports[0])
        with self._lock:
            self.state = {"status": "running", "job_id": job_id, "progress": {"current": 0, "total": 0}, "error": None}
        threading.Thread(target=self._run, args=(job_dir, job, export), daemon=True).start()
        return self.snapshot(job_id)

    def _run(self, job_dir: Path, job: dict[str, Any], export: dict[str, Any]) -> None:
        import soundfile as sf

        from .synth import load_voice, synthesize

        try:
            voice = Voice(job["voice_id"])
            items = list_recordings(voice)
            settings = load_settings(voice)
            lexicon, language = settings.get("lexicon") or {}, settings["language"]
            check_dir = job_dir / "check"
            check_dir.mkdir(exist_ok=True)
            model_path = job_dir / "export" / export["file"]
            load_voice(model_path)
            rows = []
            with self._lock:
                self.state["progress"] = {"current": 0, "total": len(items)}
            for i, r in enumerate(items):
                wav_path = check_dir / f"{r['id']}.wav"
                wav_path.write_bytes(synthesize(model_path, pronounce(r["text"], lexicon, language), 1.0, 0.667, 0.8))
                synth, sr_s = sf.read(str(wav_path), dtype="float32", always_2d=True)
                ref, sr_r = sf.read(str(voice.recordings_dir / f"{r['id']}.wav"), dtype="float32", always_2d=True)
                if sr_s != sr_r:
                    import librosa

                    synth = librosa.resample(synth[:, 0], orig_sr=sr_s, target_sr=sr_r)[:, None]
                rows.append({"id": r["id"], "text": r["text"], "duration": r["duration"], "distance": round(mel_distance(ref[:, 0], synth[:, 0], sr_r), 4)})
                with self._lock:
                    self.state["progress"] = {"current": i + 1, "total": len(items)}
            distances = [row["distance"] for row in rows]
            median = statistics.median(distances) if distances else 0.0
            spread = statistics.pstdev(distances) if len(distances) > 1 else 0.0
            for row in rows:
                row["z"] = round((row["distance"] - median) / spread, 2) if spread > 0 else 0.0
                row["flagged"] = row["z"] > Z_THRESHOLD
            rows.sort(key=lambda row: -row["distance"])
            result = {"job_id": job_dir.name, "variant": export["variant"], "created_at": now(), "count": len(rows), "median": round(median, 4), "flagged": sum(1 for row in rows if row["flagged"]), "items": rows}
            (check_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
            # the recording list reads the latest check of the voice
            (voice.dir / CHECK_FILE).write_text(json.dumps({"job_id": job_dir.name, "created_at": result["created_at"], "flagged": [row["id"] for row in rows if row["flagged"]]}))
            # remove the synthesised takes nobody will listen to; the suspicious ones stay for comparison
            keep = {row["id"] for row in rows[:30]}
            for path in check_dir.glob("*.wav"):
                if path.stem not in keep:
                    path.unlink(missing_ok=True)
            with self._lock:
                self.state.update(status="done")
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.state.update(status="failed", error=str(exc))


checker = Checker()


@router.post("/jobs/{job_id}/check")
def post_check(job_id: str):
    return checker.start(job_id)


@router.get("/jobs/{job_id}/check")
def get_check(job_id: str):
    return checker.snapshot(job_id)


@router.get("/jobs/{job_id}/check/audio/{rid}")
def get_check_audio(job_id: str, rid: str):
    if not SAFE.match(rid or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad recording id"})
    path = find_job_dir(job_id) / "check" / f"{rid}.wav"
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "No synthesised take for this recording"})
    return FileResponse(path, media_type="audio/wav")
