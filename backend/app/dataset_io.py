"""Dataset files: export (LJSpeech layout), import of such an archive, and MP3 blocks for cloud cloning services."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .audio import normalize_wav
from .config import LANGUAGES, SAMPLE_RATE, load_settings, now, slugify, write_settings
from .recordings import list_recordings, store_recording, total_minutes
from .voices import consent_statement, has_consent, require_voice

router = APIRouter(prefix="/api", tags=["dataset"])


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
