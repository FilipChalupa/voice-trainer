"""System information: GPU availability, PyTorch CUDA build, disk space, app version and update check."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from .config import DATA_DIR

router = APIRouter(prefix="/api", tags=["system"])
_cache: dict[str, Any] = {"at": 0.0, "value": None}
_update_cache: dict[str, Any] = {"at": 0.0, "value": None}
REPO = os.environ.get("GITHUB_REPO", "FilipChalupa/voice-trainer")


def app_version() -> str:
    env = os.environ.get("APP_VERSION", "").strip()
    if env:
        return env
    for candidate in (Path(__file__).resolve().parent.parent / "VERSION", Path(__file__).resolve().parent.parent.parent / "VERSION"):
        if candidate.is_file():
            return candidate.read_text().strip()
    return "dev"


def version_tuple(text: str) -> tuple[int, ...]:
    out = []
    for piece in text.lstrip("v").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out[:3])


def latest_release() -> dict[str, Any] | None:
    now = time.time()
    if now - _update_cache["at"] < 6 * 3600:
        return _update_cache["value"]
    _update_cache["at"] = now
    try:
        import requests

        res = requests.get(f"https://api.github.com/repos/{REPO}/tags?per_page=5", timeout=5, headers={"Accept": "application/vnd.github+json"})
        tags = [t["name"] for t in res.json()] if res.ok else []
        versions = sorted((t for t in tags if version_tuple(t) > (0,)), key=version_tuple, reverse=True)
        _update_cache["value"] = {"latest": versions[0], "url": f"https://github.com/{REPO}/releases"} if versions else None
    except Exception:  # noqa: BLE001
        _update_cache["value"] = None
    return _update_cache["value"]


def nvidia_smi() -> dict[str, Any] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    first = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
    try:
        return {"name": first[0], "memory_total_mb": int(float(first[1])), "memory_used_mb": int(float(first[2])), "driver": first[3]}
    except (IndexError, ValueError):
        return None


def torch_cuda() -> bool:
    """True when the installed PyTorch wheel ships CUDA libraries (checked without importing torch)."""
    try:
        version = metadata.version("torch")
    except metadata.PackageNotFoundError:
        return False
    if "+cpu" in version:
        return False
    if "+cu" in version:
        return True
    # CUDA wheels pull in the NVIDIA runtime packages (nvidia-cudnn-cu12 / -cu13, ...)
    for dist in metadata.distributions():
        name = (dist.metadata["Name"] or "").lower()
        if name.startswith("nvidia-cudnn"):
            return True
    return False


def system_info() -> dict[str, Any]:
    now = time.time()
    if _cache["value"] is not None and now - _cache["at"] < 10:
        return _cache["value"]
    gpu = nvidia_smi()
    release = latest_release()
    current = app_version()
    usage = shutil.disk_usage(DATA_DIR)
    value = {
        "version": current,
        "latest_version": release["latest"] if release else None,
        "update_available": bool(release and version_tuple(release["latest"]) > version_tuple(current)),
        "releases_url": release["url"] if release else f"https://github.com/{REPO}",
        "gpu": gpu,
        "gpu_available": gpu is not None,
        "torch_cuda": torch_cuda(),
        "cpu_count": os.cpu_count(),
        "disk_free_gb": round(usage.free / (1 << 30), 1),
        "disk_total_gb": round(usage.total / (1 << 30), 1),
    }
    _cache.update(at=now, value=value)
    return value


@router.get("/system")
def get_system():
    return system_info()
