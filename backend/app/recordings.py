"""Recordings of read sentences: upload, list, edit text, delete/restore, prompts, the dataset report and export."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import prompts
from .audio import analyze, has_speech, normalize_wav, trim_edges
from .config import LANGUAGES, MIN_MINUTES, RECOMMENDED_MINUTES, SAMPLE_RATE, TARGET_MINUTES, Voice, load_settings, now, slugify, write_settings
from .voices import consent_statement, has_consent, require_voice

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
        if r["id"] in suspicious:
            r["quality"] = {**r["quality"], "issues": [*r["quality"]["issues"], "model_mismatch"]}
    return items


def _flagged_by_model(voice: Voice) -> set[str]:
    """Recordings the trained voice could not reproduce (see check.py); empty until a check has run."""
    path = voice.dir / "model_check.json"
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()).get("flagged") or [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return set()


def total_minutes(items: list[dict[str, Any]]) -> float:
    return sum(r["duration"] for r in items) / 60.0


@router.get("/recordings")
def get_recordings():
    voice = require_voice()
    items = list_recordings(voice)
    return {"items": items, "count": len(items), "minutes": round(total_minutes(items), 2)}


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
        "issues": {issue: sum(1 for r in items if issue in r["quality"]["issues"]) for issue in ("cut_start", "cut_end", "clipping", "too_quiet", "silent", "text_mismatch", "level_mismatch", "noisy", "model_mismatch")},
        "rare_letters": rare,
        "duration_histogram": buckets,
        "has_consent": has_consent(voice),
        "ready": has_consent(voice) and minutes >= MIN_MINUTES,
    }


@router.get("/dataset")
def get_dataset():
    return dataset_report(require_voice())


# ----- export ---------------------------------------------------------------
EXPORT_README = """{name} - speech dataset exported from Voice Trainer

{count} recordings, {minutes} minutes, {rate} Hz mono 16-bit WAV, language: {language}
Voice owner: {owner}
{consent}

Files
  wavs/<id>.wav         one read sentence per file
  metadata.csv          LJSpeech format: <id>|<text>|<text>   (Coqui TTS, StyleTTS2, the original Piper preprocess, ...)
  metadata_piper.csv    <id>.wav|<text>                        (piper.train: --data.csv_path with --data.audio_dir wavs)
  dataset.json          the same list with durations and quality notes
  consent.wav           the owner's spoken consent, when it was recorded

The texts are exactly what was read, with punctuation, not normalised.
This is a recording of a real person's voice. Use it only in ways the owner agreed to.
"""


def _one_line(text: str) -> str:
    # "|" separates the columns and a line is one recording
    return " ".join(text.replace("|", " ").split())


@router.get("/dataset/export")
def export_dataset():
    """The recordings with their transcripts as a ZIP in the LJSpeech layout, for training elsewhere."""
    voice = require_voice()
    items = list_recordings(voice)
    if not items:
        raise HTTPException(404, {"code": "no_recordings", "message": "There are no recordings to export"})
    settings = load_settings(voice)
    slug = slugify(settings["name"])
    width = max(4, len(str(len(items))))
    consent = settings.get("consent") if has_consent(voice) else None
    entries = []
    fd, tmp = tempfile.mkstemp(prefix="dataset-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            for n, r in enumerate(items, start=1):
                name = f"{slug}_{n:0{width}d}"
                zf.write(voice.recordings_dir / f"{r['id']}.wav", f"wavs/{name}.wav")
                entries.append({"id": name, "text": _one_line(r["text"]), "duration": r["duration"], "issues": r["quality"]["issues"], "recorded_at": r["created"]})
            zf.writestr("metadata.csv", "".join(f"{e['id']}|{e['text']}|{e['text']}\n" for e in entries))
            zf.writestr("metadata_piper.csv", "".join(f"{e['id']}.wav|{e['text']}\n" for e in entries))
            if consent:
                zf.write(voice.consent_file, "consent.wav")
            minutes = round(total_minutes(items), 2)
            info = {
                "name": settings["name"],
                "owner": settings["owner"],
                "language": settings["language"],
                "piper_language": LANGUAGES[settings["language"]]["piper"],
                "espeak_voice": LANGUAGES[settings["language"]]["espeak"],
                "sample_rate": SAMPLE_RATE,
                "count": len(entries),
                "minutes": minutes,
                "consent": consent,
                "exported_at": now(),
                "recordings": entries,
            }
            zf.writestr("dataset.json", json.dumps(info, indent=2, ensure_ascii=False))
            consent_line = f"Spoken consent recorded {consent.get('at', '')}: \"{consent.get('text', '')}\"" if consent else "Spoken consent: not recorded"
            zf.writestr("README.txt", EXPORT_README.format(name=settings["name"], count=len(entries), minutes=minutes, rate=SAMPLE_RATE, language=settings["language"], owner=settings["owner"], consent=consent_line))
    except Exception:
        os.unlink(tmp)
        raise
    return FileResponse(tmp, media_type="application/zip", filename=f"{slug}-dataset.zip", background=BackgroundTask(os.unlink, tmp))


AUDIO_EXT = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".webm")


def _parse_metadata(text: str) -> list[tuple[str, str]]:
    """Rows of ``id|text`` or ``id|text|normalised text`` (LJSpeech) or ``file.wav|text`` (Piper)."""
    rows = []
    for line in text.splitlines():
        parts = [c.strip() for c in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        name = parts[0]
        for ext in AUDIO_EXT:
            if name.lower().endswith(ext):
                name = name[: -len(ext)]
        sentence = next((c for c in reversed(parts[1:]) if c), "")
        if sentence:
            rows.append((name, sentence))
    return rows


@router.post("/dataset/import")
async def import_dataset(file: UploadFile = File(...)):
    """Adds the recordings of a ZIP in the LJSpeech layout (as written by the export) to the current voice."""
    voice = require_voice()
    settings = load_settings(voice)
    fd, tmp = tempfile.mkstemp(prefix="import-", suffix=".zip")
    imported, skipped, consent_imported = 0, [], False
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1 << 20):
                out.write(chunk)
        try:
            zf = zipfile.ZipFile(tmp)
        except zipfile.BadZipFile as exc:
            raise HTTPException(400, {"code": "bad_zip", "message": "The file is not a ZIP archive"}) from exc
        with zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            by_base = {n.split("/")[-1].lower(): n for n in names}
            metadata = next((by_base[k] for k in ("metadata.csv", "metadata_piper.csv") if k in by_base), None)
            if metadata is None:
                metadata = next((n for n in names if n.lower().endswith(".csv")), None)
            if metadata is None:
                raise HTTPException(400, {"code": "no_metadata", "message": "The archive has no metadata.csv with the transcripts"})
            rows = _parse_metadata(zf.read(metadata).decode("utf-8-sig", errors="replace"))
            if not rows:
                raise HTTPException(400, {"code": "no_metadata", "message": "metadata.csv has no usable rows"})
            audio_by_stem: dict[str, str] = {}
            for n in names:
                base = n.split("/")[-1]
                stem, dot, ext = base.rpartition(".")
                if dot and f".{ext.lower()}" in AUDIO_EXT and stem.lower() not in audio_by_stem:
                    audio_by_stem[stem.lower()] = n
            for name, sentence in rows:
                member = audio_by_stem.get(name.lower())
                if member is None:
                    skipped.append({"id": name, "reason": "missing_audio"})
                    continue
                try:
                    store_recording(voice, zf.read(member), sentence, source="import")
                    imported += 1
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {}
                    skipped.append({"id": name, "reason": detail.get("code", "error")})
            # the owner's consent travels with an export of the same person
            info = json.loads(zf.read(by_base["dataset.json"])) if "dataset.json" in by_base else {}
            consent = info.get("consent") if isinstance(info, dict) else None
            if consent and "consent.wav" in by_base and not has_consent(voice) and consent.get("owner") == settings["owner"]:
                try:
                    wav, duration = normalize_wav(zf.read(by_base["consent.wav"]))
                    voice.consent_file.write_bytes(wav)
                    settings["consent"] = {"text": consent_statement(voice), "owner": settings["owner"], "at": consent.get("at") or now(), "duration": round(duration, 2), "imported": True}
                    write_settings(voice, settings)
                    consent_imported = True
                except Exception:  # noqa: BLE001  (a broken consent file just is not imported)
                    pass
    finally:
        os.unlink(tmp)
    items = list_recordings(voice)
    return {"imported": imported, "skipped": skipped, "consent_imported": consent_imported, "count": len(items), "minutes": round(total_minutes(items), 2)}


# ----- blocks for cloud voice cloning ---------------------------------------
BLOCK_SECONDS = 8 * 60  # ~7.7 MB of 128 kbps MP3, under the per-file limit of the cloning services
BLOCK_PAUSE = 0.6
BLOCKS_README = """{name} - {count} recordings ({minutes} min) joined into {blocks} MP3 block(s) of up to 8 minutes

Cloud voice cloning services (ElevenLabs and others) do not accept a trained model, only audio samples of the
voice. They prefer a few longer files over hundreds of short ones, so the sentences are joined here with short
pauses. block_NN.txt holds the sentences of each block in order.

ElevenLabs: Voices -> Add a new voice -> Instant Voice Cloning (1-3 minutes of audio are enough) or Professional
Voice Cloning (30 minutes to 3 hours, better quality, includes a verification that it is your own voice).
Upload the block files there. Check their current limits and terms; they change.

Voice owner: {owner}. Only clone a voice with the permission of its owner.
"""


def _mp3(audio, sample_rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-i", "-", "-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "-"]
    return subprocess.run(cmd, input=pcm, capture_output=True, check=True).stdout


@router.get("/dataset/export/blocks")
def export_blocks():
    """The recordings joined into long MP3 blocks, the input format of cloud voice cloning services."""
    import numpy as np
    import soundfile as sf

    voice = require_voice()
    items = list_recordings(voice)
    if not items:
        raise HTTPException(404, {"code": "no_recordings", "message": "There are no recordings to export"})
    settings = load_settings(voice)
    slug = slugify(settings["name"])
    pause = np.zeros(int(SAMPLE_RATE * BLOCK_PAUSE), dtype=np.float32)
    blocks: list[tuple[list, list[str]]] = [([], [])]
    seconds = 0.0
    for r in items:
        data, sr = sf.read(str(voice.recordings_dir / f"{r['id']}.wav"), dtype="float32", always_2d=True)
        audio = data[:, 0]
        if seconds > 0 and seconds + len(audio) / sr > BLOCK_SECONDS:
            blocks.append(([], []))
            seconds = 0.0
        blocks[-1][0].extend([audio, pause])
        blocks[-1][1].append(r["text"])
        seconds += len(audio) / sr + BLOCK_PAUSE
    fd, tmp = tempfile.mkstemp(prefix="blocks-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for n, (parts, texts) in enumerate(blocks, start=1):
                zf.writestr(f"{slug}_block_{n:02d}.mp3", _mp3(np.concatenate(parts), SAMPLE_RATE))
                zf.writestr(f"{slug}_block_{n:02d}.txt", "\n".join(texts) + "\n")
            minutes = round(total_minutes(items), 1)
            zf.writestr("README.txt", BLOCKS_README.format(name=settings["name"], count=len(items), minutes=minutes, blocks=len(blocks), owner=settings["owner"]))
    except Exception:
        os.unlink(tmp)
        raise
    return FileResponse(tmp, media_type="application/zip", filename=f"{slug}-voice-samples.zip", background=BackgroundTask(os.unlink, tmp))
