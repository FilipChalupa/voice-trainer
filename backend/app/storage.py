"""What takes up space in /data, and the two things that are safe to throw away (trash, run caches)."""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .config import BASE_DIR, DATA_DIR, PROMPTS_DIR, VOICES_DIR, Voice, list_voices, load_settings

router = APIRouter(prefix="/api", tags=["storage"])
_cache: dict[str, Any] = {"at": 0.0, "value": None}
_lock = threading.Lock()


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _job_parts(job_dir: Path) -> dict[str, int]:
    return {
        "checkpoints": dir_size(job_dir / "checkpoints"),
        "exports": dir_size(job_dir / "export"),
        "cache": dir_size(job_dir / "cache") + dir_size(job_dir / "lightning_logs"),
        "previews": dir_size(job_dir / "previews") + dir_size(job_dir / "check"),
    }


def overview() -> dict[str, Any]:
    with _lock:
        if _cache["value"] is not None and time.time() - _cache["at"] < 20:
            return _cache["value"]
    voices = []
    for entry in list_voices():
        voice = Voice(entry["id"])
        settings = load_settings(voice)
        jobs = []
        if voice.jobs_dir.exists():
            for job_dir in sorted(voice.jobs_dir.iterdir(), reverse=True):
                if job_dir.is_dir():
                    parts = _job_parts(job_dir)
                    jobs.append({"job_id": job_dir.name, **parts, "total": sum(parts.values()) + dir_size(job_dir / "dataset") + dir_size(job_dir / "train.log")})
        recordings = dir_size(voice.recordings_dir) - dir_size(voice.recordings_dir / ".trash")
        trash = dir_size(voice.recordings_dir / ".trash")
        voices.append(
            {
                "id": voice.id,
                "name": settings["name"],
                "recordings": recordings,
                "trash": trash,
                "jobs": jobs,
                "jobs_total": sum(j["total"] for j in jobs),
                "cache_total": sum(j["cache"] for j in jobs),
                "total": recordings + trash + sum(j["total"] for j in jobs) + dir_size(voice.consent_file),
            }
        )
    base = {
        "checkpoints": sum(dir_size(p) for p in BASE_DIR.glob("*.ckpt")),
        "whisper": dir_size(BASE_DIR / "whisper"),
        "base_voices": dir_size(BASE_DIR / "voices"),
        "torch_hub": dir_size(BASE_DIR / "torch_hub"),
        "prompts": dir_size(PROMPTS_DIR),
    }
    usage = shutil.disk_usage(DATA_DIR)
    total = dir_size(DATA_DIR)
    value = {
        "total": total,
        "disk_free": usage.free,
        "disk_total": usage.total,
        "base": base,
        "base_total": sum(base.values()),
        "voices": voices,
        "reclaimable": {"trash": sum(v["trash"] for v in voices), "cache": sum(v["cache_total"] for v in voices)},
    }
    with _lock:
        _cache.update(at=time.time(), value=value)
    return value


def _invalidate() -> None:
    with _lock:
        _cache["value"] = None


@router.get("/storage")
def get_storage():
    return overview()


@router.post("/storage/empty-trash")
def empty_trash():
    """Deleted recordings of every voice are gone for good."""
    removed = 0
    for entry in list_voices():
        trash = Voice(entry["id"]).recordings_dir / ".trash"
        if trash.exists():
            removed += dir_size(trash)
            shutil.rmtree(trash, ignore_errors=True)
    _invalidate()
    return {"freed": removed}


@router.post("/storage/clear-cache")
def clear_cache():
    """Spectrogram caches and Lightning logs of finished runs; they are rebuilt when a run continues."""
    from .jobs import manager

    if manager.is_running():
        raise HTTPException(409, {"code": "already_running", "message": "Training is running; clear the caches afterwards"})
    removed = 0
    for entry in list_voices():
        jobs_dir = Voice(entry["id"]).jobs_dir
        if not jobs_dir.exists():
            continue
        for job_dir in jobs_dir.iterdir():
            for sub in ("cache", "lightning_logs"):
                target = job_dir / sub
                if target.is_dir():
                    removed += dir_size(target)
                    shutil.rmtree(target, ignore_errors=True)
    _invalidate()
    return {"freed": removed}
