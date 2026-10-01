"""Recordings of read sentences: upload, list, edit text, delete/restore, prompts and the dataset report."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import prompts
from .audio import analyze, has_speech, normalize_wav, trim_edges
from .config import MIN_MINUTES, RECOMMENDED_MINUTES, TARGET_MINUTES, Voice, load_settings
from .voices import has_consent, require_voice

router = APIRouter(prefix="/api", tags=["recordings"])

SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")
TRASH_KEEP = 100
_lock = threading.RLock()
_analysis_cache: dict[tuple[str, int, str], dict] = {}


def load_index(voice: Voice) -> dict[str, dict[str, Any]]:
    path = voice.recordings_file
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_index(voice: Voice, index: dict[str, dict[str, Any]]) -> None:
    with _lock:
        voice.recordings_dir.mkdir(parents=True, exist_ok=True)
        voice.recordings_file.write_text(json.dumps(index, ensure_ascii=False, indent=1))


def _check_id(rid: str) -> None:
    if not SAFE_ID.match(rid or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad recording id"})


def _analysis(path: Path, text: str) -> dict:
    key = (str(path), int(path.stat().st_mtime_ns), text)
    cached = _analysis_cache.get(key)
    if cached is None:
        cached = analyze(path, text)
        if len(_analysis_cache) > 5000:
            _analysis_cache.clear()
        _analysis_cache[key] = cached
    return cached


def describe(voice: Voice, rid: str, entry: dict[str, Any]) -> dict[str, Any]:
    path = voice.recordings_dir / f"{rid}.wav"
    info = _analysis(path, entry.get("text", ""))
    return {
        "id": rid,
        "text": entry.get("text", ""),
        "prompt_id": entry.get("prompt_id"),
        "reviewed": bool(entry.get("reviewed")),
        "verify": entry.get("verify"),  # Whisper check of the flow mode: {status, transcript, similarity}
        "source": entry.get("source"),  # None = recorded here, "import" = from a dataset file, "transcribed" = cut from a long recording
        "created": entry.get("created") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "duration": info["duration"],
        "url": f"/api/recordings/{rid}/audio",
        "peaks": info["peaks"],
        "quality": info["quality"],
    }


LEVEL_TOLERANCE_DB = 6.0  # louder/quieter than the typical recording by more than this = a different setup
NOISE_TOLERANCE_DB = 10.0


def flag_inconsistent(items: list[dict[str, Any]]) -> None:
    """Marks recordings whose loudness or background noise differs a lot from the rest of the set.

    Such takes usually come from another microphone, distance or room; a voice trained on them sounds uneven.
    """
    levels = [r["quality"].get("speech_db") for r in items if r["quality"].get("speech_db") is not None]
    noises = [r["quality"].get("noise_db") for r in items if r["quality"].get("noise_db") is not None]
    if len(levels) < 5:
        return
    level_median = sorted(levels)[len(levels) // 2]
    noise_median = sorted(noises)[len(noises) // 2] if noises else None
    for r in items:
        q = r["quality"]
        issues = list(q["issues"])
        if q.get("speech_db") is not None and abs(q["speech_db"] - level_median) > LEVEL_TOLERANCE_DB:
            issues.append("level_mismatch")
        if noise_median is not None and q.get("noise_db") is not None and q["noise_db"] > max(noise_median + NOISE_TOLERANCE_DB, -55.0):
            issues.append("noisy")
        r["quality"] = {**q, "issues": issues}


def list_recordings(voice: Voice) -> list[dict[str, Any]]:
    index = load_index(voice)
    items = []
    for rid, entry in index.items():
        if (voice.recordings_dir / f"{rid}.wav").exists():
            items.append(describe(voice, rid, entry))
    items.sort(key=lambda r: r["created"])
    flag_inconsistent(items)
    suspicious = _flagged_by_model(voice)
    for r in items:
        extra = []
        if r["id"] in suspicious:
            extra.append("model_mismatch")
        if (r.get("verify") or {}).get("status") == "mismatch":
            extra.append("transcript_mismatch")
        if extra:
            r["quality"] = {**r["quality"], "issues": [*r["quality"]["issues"], *extra]}
    return items


def _flagged_by_model(voice: Voice) -> set[str]:
    """Recordings the trained voice could not reproduce (see check.py); empty until a check has run."""
    path = voice.dir / "model_check.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
        if not (voice.jobs_dir / str(data.get("job_id"))).is_dir():
            return set()  # the run was pruned or deleted; its verdicts no longer apply
        return set(data.get("flagged") or [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return set()


def total_minutes(items: list[dict[str, Any]]) -> float:
    return sum(r["duration"] for r in items) / 60.0


@router.get("/recordings")
def get_recordings(brief: bool = False, ids: str | None = None):
    """``brief`` leaves the waveform peaks out (status polling), ``ids`` limits the answer to those recordings;
    count and minutes always describe the whole set."""
    voice = require_voice()
    items = list_recordings(voice)
    count, minutes = len(items), round(total_minutes(items), 2)
    if ids:
        wanted = set(ids.split(","))
        items = [r for r in items if r["id"] in wanted]
    if brief:
        items = [{**r, "peaks": []} for r in items]
    return {"items": items, "count": count, "minutes": minutes}


def store_recording(voice: Voice, raw: bytes, text: str, prompt_id: str | None = None, source: str | None = None) -> dict[str, Any]:
    """Normalises, trims and files one recording; the transcript is stored with it."""
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) < 3:
        raise HTTPException(400, {"code": "text_required", "message": "The transcript of the recording is required"})
    if not raw:
        raise HTTPException(400, {"code": "empty_upload", "message": "Empty upload"})
    try:
        wav, duration = normalize_wav(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, {"code": "bad_audio", "message": f"Could not decode audio: {exc}"}) from exc
    wav, duration = trim_edges(wav)
    if duration < 0.5 or not has_speech(wav):
        raise HTTPException(400, {"code": "silent_recording", "message": "No speech detected in the recording"})
    if duration > 30:
        raise HTTPException(400, {"code": "too_long", "message": "Recording is too long (max 30 s per sentence)"})
    rid = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    (voice.recordings_dir / f"{rid}.wav").write_bytes(wav)
    with _lock:
        index = load_index(voice)
        # re-recording a prompt replaces the earlier take
        if prompt_id:
            for old_id, entry in list(index.items()):
                if entry.get("prompt_id") == prompt_id:
                    _to_trash(voice, old_id)
                    index.pop(old_id, None)
        entry = {"text": text, "prompt_id": prompt_id or prompts.prompt_id(text), "created": datetime.now(timezone.utc).isoformat()}
        if source:
            entry["source"] = source
        index[rid] = entry
        save_index(voice, index)
    return describe(voice, rid, index[rid])


@router.post("/recordings")
async def upload_recording(file: UploadFile = File(...), text: str = Form(...), prompt_id: str | None = Form(None)):
    return store_recording(require_voice(), await file.read(), text, prompt_id)


def _trash_dir(voice: Voice) -> Path:
    path = voice.recordings_dir / ".trash"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _to_trash(voice: Voice, rid: str) -> dict[str, Any] | None:
    src = voice.recordings_dir / f"{rid}.wav"
    if not src.exists():
        return None
    trash = _trash_dir(voice)
    entry = load_index(voice).get(rid, {})
    src.rename(trash / f"{rid}.wav")
    (trash / f"{rid}.json").write_text(json.dumps(entry, ensure_ascii=False))
    old = sorted(trash.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    for stale in old[:-TRASH_KEEP]:
        stale.unlink(missing_ok=True)
        stale.with_suffix(".json").unlink(missing_ok=True)
    return entry


@router.get("/recordings/{rid}/audio")
def get_audio(rid: str):
    _check_id(rid)
    path = require_voice().recordings_dir / f"{rid}.wav"
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Recording not found"})
    return FileResponse(path, media_type="audio/wav", filename=f"{rid}.wav")


@router.put("/recordings/{rid}")
async def put_recording(rid: str, body: dict[str, Any]):
    _check_id(rid)
    voice = require_voice()
    text = re.sub(r"\s+", " ", str(body.get("text", "")).strip()) if body.get("text") is not None else None
    if text is not None and len(text) < 3:
        raise HTTPException(400, {"code": "text_required", "message": "The transcript of the recording is required"})
    with _lock:
        index = load_index(voice)
        if rid not in index:
            raise HTTPException(404, {"code": "not_found", "message": "Recording not found"})
        if text is not None:
            index[rid]["text"] = text
            if (index[rid].get("verify") or {}).get("status") == "mismatch":
                index[rid]["verify"] = {**index[rid]["verify"], "status": "ok", "edited": True}
        if "reviewed" in body:
            # a person listened to it and confirmed the text; warnings then no longer queue it for review
            index[rid]["reviewed"] = bool(body["reviewed"])
        save_index(voice, index)
    return describe(voice, rid, index[rid])


@router.delete("/recordings/{rid}")
def delete_recording(rid: str):
    _check_id(rid)
    voice = require_voice()
    with _lock:
        if _to_trash(voice, rid) is None:
            raise HTTPException(404, {"code": "not_found", "message": "Recording not found"})
        index = load_index(voice)
        index.pop(rid, None)
        save_index(voice, index)
    return {"deleted": rid, "restorable": True}


@router.post("/recordings/{rid}/redo")
def redo_recording(rid: str):
    """Record the sentence again: the take goes to the trash and its sentence comes up next."""
    _check_id(rid)
    voice = require_voice()
    with _lock:
        index = load_index(voice)
        entry = index.get(rid)
        if entry is None:
            raise HTTPException(404, {"code": "not_found", "message": "Recording not found"})
        text = entry.get("text", "")
        _to_trash(voice, rid)
        index.pop(rid, None)
        save_index(voice, index)
    pid = prompts.queue_front(voice, text)
    return {"deleted": rid, "prompt_id": pid, "text": text, "restorable": True}


@router.post("/recordings/{rid}/restore")
def restore_recording(rid: str):
    _check_id(rid)
    voice = require_voice()
    trash = _trash_dir(voice)
    src = trash / f"{rid}.wav"
    if not src.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Recording is not in the trash"})
    meta = trash / f"{rid}.json"
    entry = json.loads(meta.read_text()) if meta.exists() else {"text": ""}
    src.rename(voice.recordings_dir / f"{rid}.wav")
    meta.unlink(missing_ok=True)
    with _lock:
        index = load_index(voice)
        index[rid] = entry
        save_index(voice, index)
    return describe(voice, rid, entry)


# ----- prompts -------------------------------------------------------------------------
@router.get("/prompts")
def get_prompts(count: int = 5):
    voice = require_voice()
    recorded = {e.get("prompt_id") for e in load_index(voice).values()}
    return prompts.next_prompts(voice, recorded, max(1, min(50, count)))


@router.post("/prompts/custom")
async def post_custom_prompts(body: dict[str, Any]):
    voice = require_voice()
    added = prompts.add_custom(voice, str(body.get("text", "")))
    if added == 0:
        raise HTTPException(400, {"code": "no_sentences", "message": "No new sentences found in the text"})
    return {"added": added}


@router.post("/prompts/{pid}/skip")
def post_skip(pid: str):
    _check_id(pid)
    prompts.skip_prompt(require_voice(), pid)
    return {"skipped": pid}


# ----- dataset report --------------------------------------------------------------------
def dataset_report(voice: Voice) -> dict[str, Any]:
    items = list_recordings(voice)
    settings = load_settings(voice)
    minutes = total_minutes(items)
    durations = [r["duration"] for r in items]
    flagged = [r for r in items if r["quality"]["issues"]]
    text = " ".join(r["text"].lower() for r in items)
    alphabet = "aábcčdďeéěfghiíjklmnňoópqrřsštťuúůvwxyýzž" if settings["language"] == "cs" else "abcdefghijklmnopqrstuvwxyz"
    counts = {ch: text.count(ch) for ch in alphabet}
    rare = [ch for ch, n in counts.items() if n < 3 and ch not in "qwx"]
    buckets = [0] * 8  # 0-2, 2-4, ... 14+ seconds
    for d in durations:
        buckets[min(7, int(d // 2))] += 1
    return {
        "count": len(items),
        "minutes": round(minutes, 2),
        "mean_seconds": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "min_minutes": MIN_MINUTES,
        "recommended_minutes": RECOMMENDED_MINUTES,
        "target_minutes": TARGET_MINUTES,
        "flagged": len(flagged),
        "issues": {issue: sum(1 for r in items if issue in r["quality"]["issues"]) for issue in ("cut_start", "cut_end", "clipping", "too_quiet", "silent", "text_mismatch", "level_mismatch", "noisy", "model_mismatch", "transcript_mismatch")},
        "rare_letters": rare,
        "duration_histogram": buckets,
        "has_consent": has_consent(voice),
        "ready": has_consent(voice) and minutes >= MIN_MINUTES,
    }


@router.get("/dataset")
def get_dataset():
    return dataset_report(require_voice())
