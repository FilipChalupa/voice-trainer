"""A voice in one ZIP: recordings with their texts, the consent, the settings (lexicon, training, sound
correction) and the results of the runs with their exported voices. Checkpoints and caches stay out: they
are large and a run can be made again. The ZIP restores as a new voice, never over an existing one."""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .config import VOICES_DIR, Voice, list_voices, load_settings, select_voice, slugify, write_settings
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["backup"])

SKIP_DIRS = {"cache", "checkpoints", "dataset", "trash"}
MAX_MEMBERS = 50000
MEMBER = re.compile(r"^[A-Za-z0-9._\- ]+(/[A-Za-z0-9._\- ]+)*$")


def members(voice: Voice):
    """(path on disk, name in the archive) of everything worth keeping."""
    for path in sorted(voice.dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(voice.dir)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]) or path.suffix == ".ckpt":
            continue
        yield path, rel.as_posix()


@router.get("/backup")
def get_backup():
    voice = require_voice()
    settings = load_settings(voice)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup.json", json.dumps({"app": "voice-trainer", "voice_id": voice.id, "name": settings["name"], "language": settings["language"]}, ensure_ascii=False))
        for path, name in members(voice):
            zf.write(path, name)
    buffer.seek(0)
    filename = f"voice-{slugify(settings['name']) or voice.id}.zip"
    return StreamingResponse(buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/backup/restore")
async def post_restore(file: UploadFile = File(...)) -> dict[str, Any]:
    from .jobs import manager

    if manager.is_running():
        raise HTTPException(409, {"code": "already_running", "message": "Cannot restore while training"})
    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        meta = json.loads(zf.read("backup.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise HTTPException(400, {"code": "bad_backup", "message": "This is not a voice backup made by this app"}) from exc
    if meta.get("app") != "voice-trainer":
        raise HTTPException(400, {"code": "bad_backup", "message": "This is not a voice backup made by this app"})
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if len(names) > MAX_MEMBERS or any(not MEMBER.match(n) or ".." in n.split("/") for n in names):
        raise HTTPException(400, {"code": "bad_backup", "message": "The backup holds a path that is not allowed"})
    base = slugify(str(meta.get("voice_id") or meta.get("name") or "voice"))[:32] or "voice"
    vid, n = base, 2
    while (VOICES_DIR / vid).exists():
        vid = f"{base}-{n}"
        n += 1
    voice = Voice(vid).ensure()
    for name in names:
        if name == "backup.json":
            continue
        target = voice.dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(name))
    settings = load_settings(voice)  # validated and completed with defaults
    write_settings(voice, settings)
    select_voice(voice.id)
    return {"voice_id": voice.id, "name": settings["name"], "files": len(names) - 1, "voices": list_voices()}
