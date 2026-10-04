"""The tone of the copies that go into training: what the takes sound like, what a correction would do to them,
a suggestion that brings a boomy voice back to a neutral balance, and a processed take to listen to."""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .audio import apply_processing, eq_gain
from .config import Voice, clean_processing, load_settings
from .recordings import SAFE_ID, load_index
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["processing"])

SAMPLE_TAKES = 40
N_FFT = 2048
BANDS: list[tuple[str, float, float]] = [("sub", 20, 90), ("bass", 90, 250), ("mid", 250, 1000), ("presence", 1000, 4000), ("air", 4000, 11000)]
# bass relative to the middle band in a voice recorded at a normal distance; a close dynamic microphone adds 3-6 dB
NEUTRAL_BASS_DB = -0.5
CURVE_POINTS = 48

_cache: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


def average_spectrum(voice: Voice) -> tuple[np.ndarray, np.ndarray] | None:
    """Mean power spectrum of the speech frames of an even sample of the takes: (frequencies, power)."""
    import soundfile as sf

    ids = sorted(rid for rid in load_index(voice) if (voice.recordings_dir / f"{rid}.wav").exists())
    if not ids:
        return None
    step = max(1, len(ids) // SAMPLE_TAKES)
    chosen = ids[::step][:SAMPLE_TAKES]
    key = (voice.id, len(ids), chosen[0], chosen[-1])
    if key not in _cache:
        total, frames, rate = None, 0, 0
        for rid in chosen:
            try:
                data, sr = sf.read(str(voice.recordings_dir / f"{rid}.wav"), dtype="float32", always_2d=True)
            except Exception:  # noqa: BLE001
                continue
            x = data[:, 0]
            if x.shape[0] < N_FFT or (rate and sr != rate):
                continue
            rate = sr
            windows = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[:: N_FFT // 2] * np.hanning(N_FFT)
            power = np.abs(np.fft.rfft(windows, axis=1)) ** 2
            energy = power.sum(axis=1)
            speech = power[energy > np.percentile(energy, 60)]
            total = speech.sum(axis=0) if total is None else total + speech.sum(axis=0)
            frames += speech.shape[0]
        if total is None or not frames:
            return None
        _cache.clear()
        _cache[key] = (np.fft.rfftfreq(N_FFT, 1.0 / rate), total / frames)
    return _cache[key]


def band_levels(freqs: np.ndarray, power: np.ndarray) -> dict[str, float]:
    return {name: 10 * float(np.log10(max(power[(freqs >= lo) & (freqs < hi)].sum(), 1e-20))) for name, lo, hi in BANDS}


def analyse(freqs: np.ndarray, power: np.ndarray, processing: dict[str, float]) -> dict[str, Any]:
    after = power * eq_gain(freqs, processing) ** 2
    before_levels, after_levels = band_levels(freqs, power), band_levels(freqs, after)
    reference = before_levels["mid"]
    bands = [{"band": name, "from_hz": lo, "to_hz": hi, "before_db": round(before_levels[name] - reference, 1), "after_db": round(after_levels[name] - reference, 1)} for name, lo, hi in BANDS]
    # a smooth curve for the chart: third-octave averages on a logarithmic frequency axis
    edges = np.geomspace(40, min(10000, freqs[-1]), CURVE_POINTS + 1)
    peak = None
    curve = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (freqs >= lo / 1.12) & (freqs < hi * 1.12)
        if not mask.any():
            continue
        b, a = 10 * float(np.log10(max(power[mask].mean(), 1e-20))), 10 * float(np.log10(max(after[mask].mean(), 1e-20)))
        peak = b if peak is None else max(peak, b)
        curve.append([round(float(np.sqrt(lo * hi))), b, a])
    return {"bands": bands, "curve": [[f, round(b - peak, 1), round(a - peak, 1)] for f, b, a in curve]}


def suggest(freqs: np.ndarray, power: np.ndarray) -> dict[str, float]:
    """A high-pass under the voice and the bass cut that brings the 90-250 Hz band to a neutral balance."""
    processing = clean_processing({"highpass_hz": 80})
    levels = band_levels(freqs, power * eq_gain(freqs, processing) ** 2)
    if levels["bass"] - levels["mid"] <= NEUTRAL_BASS_DB + 0.5:
        return processing
    low, high = -12.0, 0.0
    for _ in range(20):
        middle = (low + high) / 2
        trial = {**processing, "bass_db": middle}
        levels = band_levels(freqs, power * eq_gain(freqs, trial) ** 2)
        if levels["bass"] - levels["mid"] > NEUTRAL_BASS_DB:
            high = middle
        else:
            low = middle
    return clean_processing({**processing, "bass_db": round((low + high) / 2 * 2) / 2})


def _body_processing(body: dict[str, Any], voice: Voice) -> dict[str, float]:
    return clean_processing(body["processing"]) if isinstance(body.get("processing"), dict) else load_settings(voice)["processing"]


@router.post("/processing/analysis")
def post_analysis(body: dict[str, Any]) -> dict[str, Any]:
    voice = require_voice()
    spectrum = average_spectrum(voice)
    if spectrum is None:
        return {"available": False, "bands": [], "curve": [], "suggested": None}
    return {"available": True, **analyse(*spectrum, _body_processing(body, voice)), "suggested": suggest(*spectrum)}


@router.post("/processing/preview")
def post_preview(body: dict[str, Any]) -> Response:
    """One take with the correction applied, to compare with the original by ear."""
    import soundfile as sf

    voice = require_voice()
    rid = str(body.get("recording_id", ""))
    path = voice.recordings_dir / f"{rid}.wav"
    if not SAFE_ID.match(rid) or not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Recording not found"})
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    buffer = io.BytesIO()
    sf.write(buffer, apply_processing(data[:, 0], sr, _body_processing(body, voice)), sr, subtype="PCM_16", format="WAV")
    return Response(buffer.getvalue(), media_type="audio/wav")
