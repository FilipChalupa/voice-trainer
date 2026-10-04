"""Try the trained voice: text -> speech with an exported ONNX model, and the downloadable voice bundle."""
from __future__ import annotations

import io
import json
import threading
import wave
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .base import ensure_base_voice
from .config import LANGUAGES, Voice, load_settings, pronounce
from .runs import SAFE, find_job_dir, list_exports, read_json

router = APIRouter(prefix="/api", tags=["synthesis"])
_voices: "OrderedDict[str, Any]" = OrderedDict()
_lock = threading.Lock()
MAX_LOADED = 2
MAX_TEXT = 1000


def load_voice(path: Path):
    from piper import PiperVoice

    key = f"{path}:{path.stat().st_mtime_ns}"
    with _lock:
        if key in _voices:
            _voices.move_to_end(key)
            return _voices[key]
    voice = PiperVoice.load(str(path))
    for junk in Path.cwd().glob(":memory:*"):  # onnxruntime's telemetry drops a file into the working directory
        junk.unlink(missing_ok=True)
    with _lock:
        _voices[key] = voice
        while len(_voices) > MAX_LOADED:
            _voices.popitem(last=False)
    return voice


def synthesize(path: Path, text: str, length_scale: float, noise_scale: float, noise_w_scale: float) -> bytes:
    from piper import SynthesisConfig

    voice = load_voice(path)
    config = SynthesisConfig(length_scale=length_scale, noise_scale=noise_scale, noise_w_scale=noise_w_scale)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        voice.synthesize_wav(text, wav, syn_config=config)
    return buffer.getvalue()


@router.post("/synthesize")
async def post_synthesize(body: dict[str, Any]):
    job_id = str(body.get("job_id", ""))
    name = str(body.get("file", ""))
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, {"code": "text_required", "message": "Enter some text to speak"})
    if len(text) > MAX_TEXT:
        raise HTTPException(400, {"code": "too_long", "message": f"Text is too long (max {MAX_TEXT} characters)"})
    if job_id == "base":
        # the untouched base voice, to hear what fine-tuning changed
        if name not in LANGUAGES:
            raise HTTPException(400, {"code": "bad_language", "message": "Unsupported language"})
        try:
            path = await run_in_threadpool(ensure_base_voice, name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, {"code": "download_failed", "message": f"Could not download the base voice: {exc}"}) from exc
        lexicon = {}
        language = name
        if body.get("voice_id"):
            lexicon = load_settings(Voice(str(body["voice_id"]))).get("lexicon") or {}
    else:
        if not SAFE.match(name) or not name.endswith(".onnx"):
            raise HTTPException(400, {"code": "bad_id", "message": "Bad model name"})
        job_dir = find_job_dir(job_id)
        path = job_dir / "export" / name
        if not path.exists():
            raise HTTPException(404, {"code": "not_found", "message": "Model not found"})
        job = read_json(job_dir / "job.json")
        lexicon = load_settings(Voice(job.get("voice_id") or "")).get("lexicon") or {}
        language = str(job.get("language") or "")
    text = pronounce(text, lexicon, language)

    def clamp(value: Any, default: float, low: float, high: float) -> float:
        try:
            return float(min(high, max(low, float(value))))
        except (TypeError, ValueError):
            return default

    try:
        wav = await run_in_threadpool(
            synthesize,
            path,
            text,
            clamp(body.get("length_scale"), 1.0, 0.5, 2.0),
            clamp(body.get("noise_scale"), 0.667, 0.0, 1.5),
            clamp(body.get("noise_w_scale"), 0.8, 0.0, 1.5),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, {"code": "synthesis_failed", "message": f"Synthesis failed: {exc}"}) from exc
    return Response(content=wav, media_type="audio/wav")


def usage_text(name: str, job: dict[str, Any]) -> str:
    return f"""Piper voice "{job.get('name')}" ({name}) trained with Voice Trainer on {job.get('created_at')}.
Owner of the voice: {job.get('owner')} (spoken consent recorded on {(job.get('consent') or {}).get('at')}).

Files
  {name}.onnx        the voice model
  {name}.onnx.json   its configuration (must stay next to the model, same name)

Home Assistant (Piper add-on)
  Copy both files into /share/piper (Samba or SSH add-on), restart the Piper add-on and reload the
  Wyoming integration. The voice then appears in the text-to-speech settings of your Assist pipeline.

wyoming-piper (Docker)
  services:
    piper:
      image: rhasspy/wyoming-piper
      command: --voice {name}
      volumes:
        - ./voices:/data          # put both files here
      ports:
        - "10200:10200"

Command line
  python3 -m piper -m {name}.onnx -f out.wav -- "Hello."

Other exported variants (best_mos / best_mel) are alternative checkpoints of the same run; rename the pair of
files consistently if you prefer one of them.
"""


@router.get("/jobs/{job_id}/bundle")
def get_bundle(job_id: str):
    job_dir = find_job_dir(job_id)
    job = read_json(job_dir / "job.json")
    exports = list_exports(job_dir, job_id)
    if not exports:
        raise HTTPException(404, {"code": "no_models", "message": "This run has no exported voice yet"})
    main = next((e for e in exports if e["variant"] == "last"), exports[0])
    name = main["file"][: -len(".onnx")]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in exports:
            zf.write(job_dir / "export" / e["file"], e["file"])
            zf.write(job_dir / "export" / f"{e['file']}.json", f"{e['file']}.json")
        zf.writestr("README.txt", usage_text(name, job))
        lexicon = load_settings(Voice(job.get("voice_id") or "")).get("lexicon") or {}
        if lexicon:
            # for reference only: Piper itself has no pronunciation dictionary, the respellings are applied by this app
            zf.writestr("pronunciation.json", json.dumps(lexicon, indent=2, ensure_ascii=False))
        zf.writestr("training.json", json.dumps({k: job.get(k) for k in ("name", "language", "training", "max_epochs", "recordings", "minutes", "created_at")}, indent=2, ensure_ascii=False))
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})
