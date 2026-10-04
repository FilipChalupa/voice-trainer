"""Voice routes: list / create / select / delete, settings, and the owner's spoken consent."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .audio import normalize_wav
from .config import DEFAULT_PROCESSING, DEFAULT_TRAINING, PROCESSING_LIMITS, LANGUAGES, MIN_MINUTES, RECOMMENDED_MINUTES, TARGET_MINUTES, Voice, create_voice, current_voice, delete_voice, get_voice, list_voices, load_settings, now, save_settings, select_voice, write_settings

router = APIRouter(prefix="/api", tags=["voices"])


def require_voice() -> Voice:
    voice = current_voice()
    if voice is None:
        raise HTTPException(409, {"code": "no_voice", "message": "Create a voice first"})
    return voice


def consent_statement(voice: Voice) -> str:
    settings = load_settings(voice)
    template = LANGUAGES[settings["language"]]["consent"]
    return template.format(name=settings["owner"] or "…")


def has_consent(voice: Voice) -> bool:
    return bool(load_settings(voice).get("consent")) and voice.consent_file.exists()


def _payload(voice: Voice | None) -> dict[str, Any]:
    languages = [{"id": k, "label": v["label"], "base": {kk: vv for kk, vv in v["base"].items() if kk != "url"}} for k, v in LANGUAGES.items()]
    base = {"voices": list_voices(), "current": voice.id if voice else None, "languages": languages, "defaults": DEFAULT_TRAINING, "processing_defaults": DEFAULT_PROCESSING, "processing_limits": PROCESSING_LIMITS, "minutes": {"min": MIN_MINUTES, "recommended": RECOMMENDED_MINUTES, "target": TARGET_MINUTES}}
    if voice:
        settings = load_settings(voice)
        base["voice"] = {**settings, "id": voice.id, "has_consent": has_consent(voice), "consent_statement": consent_statement(voice)}
    else:
        base["voice"] = None
    return base


@router.get("/voices")
def get_voices():
    return _payload(current_voice())


@router.post("/voices")
async def post_voice(body: dict[str, Any]):
    from .jobs import manager

    name = str(body.get("name", "")).strip()
    owner = str(body.get("owner", "")).strip()
    language = str(body.get("language", "cs"))
    if not name:
        raise HTTPException(400, {"code": "name_required", "message": "Voice name is required"})
    if not owner:
        raise HTTPException(400, {"code": "owner_required", "message": "The name of the voice owner is required"})
    if language not in LANGUAGES:
        raise HTTPException(400, {"code": "bad_language", "message": f"Unsupported language '{language}'"})
    if manager.is_running():
        raise HTTPException(409, {"code": "already_running", "message": "Cannot switch voices while training"})
    voice = create_voice(name, language, owner)
    select_voice(voice.id)
    manager.load_voice_state(voice)
    return _payload(voice)


@router.post("/voices/{vid}/select")
def post_select(vid: str):
    from .jobs import manager

    if manager.is_running():
        raise HTTPException(409, {"code": "already_running", "message": "Cannot switch voices while training"})
    try:
        voice = select_voice(vid)
    except KeyError:
        raise HTTPException(404, {"code": "not_found", "message": "Voice not found"}) from None
    manager.load_voice_state(voice)
    return _payload(voice)


@router.delete("/voices/{vid}")
def delete_voice_route(vid: str):
    from .jobs import manager

    if manager.is_running():
        raise HTTPException(409, {"code": "already_running", "message": "Cannot delete voices while training"})
    try:
        get_voice(vid)
        delete_voice(vid)
    except KeyError:
        raise HTTPException(404, {"code": "not_found", "message": "Voice not found"}) from None
    voice = current_voice()
    manager.load_voice_state(voice)
    return _payload(voice)


@router.put("/voice")
async def put_voice(body: dict[str, Any]):
    voice = require_voice()
    save_settings(voice, body if isinstance(body, dict) else {})
    return _payload(voice)


# ----- consent ------------------------------------------------------------------------
@router.post("/consent")
async def post_consent(file: UploadFile = File(...)):
    """Stores the owner's spoken consent. Training refuses to start without it."""
    voice = require_voice()
    settings = load_settings(voice)
    if not settings["owner"]:
        raise HTTPException(400, {"code": "owner_required", "message": "Set the voice owner's name first"})
    raw = await file.read()
    try:
        wav, duration = normalize_wav(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, {"code": "bad_audio", "message": f"Could not decode audio: {exc}"}) from exc
    if duration < 2.0:
        raise HTTPException(400, {"code": "too_short", "message": "The consent recording is too short – read the whole statement"})
    voice.consent_file.write_bytes(wav)
    settings["consent"] = {"text": consent_statement(voice), "owner": settings["owner"], "at": now(), "duration": round(duration, 2)}
    write_settings(voice, settings)
    return _payload(voice)


@router.get("/consent/audio")
def get_consent_audio():
    voice = require_voice()
    if not voice.consent_file.exists():
        raise HTTPException(404, {"code": "not_found", "message": "No consent recorded"})
    return FileResponse(voice.consent_file, media_type="audio/wav", filename="consent.wav")


@router.delete("/consent")
def delete_consent():
    voice = require_voice()
    settings = load_settings(voice)
    settings["consent"] = None
    write_settings(voice, settings)
    voice.consent_file.unlink(missing_ok=True)
    return _payload(voice)
