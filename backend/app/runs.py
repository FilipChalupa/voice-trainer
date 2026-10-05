"""Stored training runs: their directories, summaries, exported voices, previews and the calibration derived
from them. The live manager is in jobs.py."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .config import KEEP_JOBS, VOICES_DIR, Voice, list_voices

FINISHED = ("done", "failed", "cancelled")
SAFE = re.compile(r"^[A-Za-z0-9_.\-=]+$")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def find_job_dir(job_id: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_\-]+$", job_id or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad job id"})
    for entry in list_voices():
        candidate = VOICES_DIR / entry["id"] / "jobs" / job_id
        if candidate.is_dir():
            return candidate
    raise HTTPException(404, {"code": "not_found", "message": "Job not found"})


def list_previews(job_dir: Path, job_id: str) -> list[dict[str, Any]]:
    out = []
    preview_root = job_dir / "previews"
    if not preview_root.is_dir():
        return out
    for d in sorted(preview_root.iterdir()):
        if not d.is_dir() or not d.name.startswith("epoch_"):
            continue
        sentences = read_json(d / "sentences.json") if (d / "sentences.json").exists() else []
        files = sorted(d.glob("*.wav"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
        out.append({
            "epoch": int(d.name.split("_")[1]),
            "items": [{"url": f"/api/jobs/{job_id}/previews/{d.name}/{f.name}", "text": sentences[int(f.stem)] if isinstance(sentences, list) and f.stem.isdigit() and int(f.stem) < len(sentences) else ""} for f in files],
        })
    return out


def list_exports(job_dir: Path, job_id: str) -> list[dict[str, Any]]:
    exports = read_json(job_dir / "export" / "exports.json") if (job_dir / "export" / "exports.json").exists() else []
    out = []
    for e in exports if isinstance(exports, list) else []:
        if (job_dir / "export" / e["file"]).exists():
            out.append({**e, "url": f"/api/jobs/{job_id}/export/{e['file']}", "config_url": f"/api/jobs/{job_id}/export/{e['file']}.json"})
    return out


def job_summary(job_dir: Path, running_job_id: str | None) -> dict[str, Any] | None:
    job = read_json(job_dir / "job.json")
    if not job:
        return None
    result = read_json(job_dir / "result.json")
    status = result.get("status")
    if status is None:
        status = "running" if running_job_id == job["job_id"] else "interrupted"
    has_last = (job_dir / "checkpoints" / "last.ckpt").exists()
    exports = list_exports(job_dir, job["job_id"])
    return {
        "job_id": job["job_id"],
        "voice_id": job.get("voice_id"),
        "name": job.get("name"),
        "slug": job.get("slug"),
        "language": job.get("language"),
        "created_at": job.get("created_at"),
        "finished_at": result.get("finished_at"),
        "status": status,
        "minutes": job.get("minutes"),
        "recordings": job.get("recordings"),
        "training": job.get("training"),
        "max_epochs": job.get("max_epochs"),
        "from_job": job.get("from_job"),
        "processing": job.get("processing"),
        "intelligibility": (read_json(job_dir / "intelligibility" / "result.json") or {}).get("score"),
        "epoch": result.get("epoch"),
        "validation_last": (result.get("validation") or [None])[-1],
        "exports": exports,
        "bundle_url": f"/api/jobs/{job['job_id']}/bundle" if exports else None,
        "resumable": has_last and status in ("interrupted", "cancelled", "failed", "done"),
        "stopped_early": bool(result.get("stopped_early")),
        "previews": len(list_previews(job_dir, job["job_id"])),
    }


def list_jobs(voice: Voice, running_job_id: str | None = None) -> list[dict[str, Any]]:
    voice.ensure()
    running = running_job_id
    if running is None:
        from .jobs import manager

        if manager.is_running():
            running = manager.state.get("job_id")
    jobs = []
    for job_dir in sorted(voice.jobs_dir.iterdir(), reverse=True):
        if job_dir.is_dir():
            summary = job_summary(job_dir, running)
            if summary:
                jobs.append(summary)
    return jobs


def prune_jobs(voice: Voice, keep: int = KEEP_JOBS) -> int:
    finished = [j for j in list_jobs(voice) if j["status"] in FINISHED]
    removed = 0
    for job in finished[keep:]:
        shutil.rmtree(voice.jobs_dir / job["job_id"], ignore_errors=True)
        removed += 1
    return removed


DEFAULT_GPU_RATE = 0.2  # seconds per epoch per minute of audio, measured on an RTX 3080 with batch size 16


def calibration() -> dict[str, Any]:
    """How long an epoch takes per minute of audio on this machine, from the most recent finished run."""
    newest: dict[str, Any] | None = None
    for v in list_voices():
        voice = Voice(v["id"])
        if not voice.jobs_dir.exists():
            continue
        for job_dir in voice.jobs_dir.iterdir():
            job = read_json(job_dir / "job.json")
            result = read_json(job_dir / "result.json")
            minutes = float(job.get("minutes") or 0)
            if result.get("epoch_seconds") and minutes > 0 and (newest is None or (result.get("finished_at") or "") > newest["finished_at"]):
                newest = {"finished_at": result.get("finished_at") or "", "rate": result["epoch_seconds"] / minutes, "device": result.get("device")}
    if newest:
        return {"rate": round(newest["rate"], 4), "basis": "history", "device": newest["device"]}
    from .system import nvidia_smi, torch_cuda

    if nvidia_smi() is not None and torch_cuda():
        return {"rate": DEFAULT_GPU_RATE, "basis": "default", "device": "cuda"}
    return {"rate": None, "basis": "none", "device": "cpu"}
