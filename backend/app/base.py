"""Base Piper checkpoints to fine-tune from: status and download with progress."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import requests
from fastapi import APIRouter, HTTPException

from .config import BASE_DIR, LANGUAGES

router = APIRouter(prefix="/api", tags=["base"])
_downloads: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def base_path(language: str) -> Path:
    return BASE_DIR / LANGUAGES[language]["base"]["file"]


def is_installed(language: str) -> bool:
    path = base_path(language)
    return path.exists() and path.stat().st_size > 100_000_000


def _set(language: str, **fields) -> None:
    with _lock:
        _downloads.setdefault(language, {}).update(fields)


def download(language: str, progress: Callable[[dict], None] | None = None) -> Path:
    """Blocking download of the language's base checkpoint (~800 MB). Safe to call from a thread."""
    meta = LANGUAGES[language]["base"]
    target = base_path(language)
    part = target.with_suffix(".part")
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    _set(language, state="downloading", received=0, total=None, error=None)
    try:
        with requests.get(meta["url"], stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0) or None
            received = 0
            with open(part, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
                    received += len(chunk)
                    _set(language, received=received, total=total)
                    if progress:
                        progress({"received": received, "total": total})
        part.rename(target)
        if not is_installed(language):
            raise RuntimeError("Downloaded checkpoint is incomplete")
        _set(language, state="done")
        return target
    except Exception as exc:  # noqa: BLE001
        part.unlink(missing_ok=True)
        _set(language, state="error", error=str(exc))
        raise


def status() -> list[dict[str, Any]]:
    out = []
    for language, meta in LANGUAGES.items():
        base = meta["base"]
        out.append({
            "language": language,
            "label": meta["label"],
            "name": base["name"],
            "size_mb": base["size_mb"],
            "license": base["license"],
            "installed": is_installed(language),
            "download": _downloads.get(language),
        })
    return out


@router.get("/base")
def get_base():
    return {"items": status()}


@router.post("/base/{language}/download")
def post_download(language: str):
    if language not in LANGUAGES:
        raise HTTPException(404, {"code": "not_found", "message": "Unknown language"})
    with _lock:
        current = _downloads.get(language)
        if current and current.get("state") == "downloading":
            return current

    def run() -> None:
        try:
            download(language)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=run, daemon=True).start()
    return {"state": "downloading"}
