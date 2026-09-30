"""FastAPI application: API routers + static frontend."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import base, check, dataset_io, importer, jobs, paragraphs, recordings, storage, synth, system, voices
from .config import DATA_DIR

app = FastAPI(title="Voice Trainer", version=system.app_version())

APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
APP_USER = os.environ.get("APP_USER", "admin").strip() or "admin"


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    path = request.url.path
    if not APP_PASSWORD or path == "/api/health" or path.startswith("/assets/"):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    ok = False
    if header.lower().startswith("basic "):
        try:
            user, _, password = base64.b64decode(header[6:]).decode().partition(":")
            ok = secrets.compare_digest(user, APP_USER) and secrets.compare_digest(password, APP_PASSWORD)
        except Exception:  # noqa: BLE001
            ok = False
    if not ok:
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="voice-trainer"'})
    return await call_next(request)


for module in (voices, recordings, dataset_io, paragraphs, base, jobs, importer, synth, check, storage, system):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"ok": True, "data_dir": str(DATA_DIR)}


STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
