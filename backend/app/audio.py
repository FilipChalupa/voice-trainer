"""Audio normalisation and analysis: everything stored is 22.05 kHz / mono / 16-bit PCM WAV."""
from __future__ import annotations

import io
import shutil
import subprocess
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .config import SAMPLE_RATE

PEAK_BUCKETS = 64


def _ffmpeg_convert(raw: bytes) -> bytes | None:
    if shutil.which("ffmpeg") is None:
        return None
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", "-f", "wav", "pipe:1"],
        input=raw,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _python_convert(raw: bytes) -> bytes:
    data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SAMPLE_RATE:
        g = gcd(sr, SAMPLE_RATE)
        mono = resample_poly(mono, SAMPLE_RATE // g, sr // g).astype(np.float32)
    out = io.BytesIO()
    sf.write(out, np.clip(mono, -1.0, 1.0), SAMPLE_RATE, subtype="PCM_16", format="WAV")
    return out.getvalue()


def normalize_wav(raw: bytes) -> tuple[bytes, float]:
    """Returns (wav_bytes, duration_seconds) in the project's canonical format."""
    converted = _ffmpeg_convert(raw)
    if converted is None:
        converted = _python_convert(raw)
    info = sf.info(io.BytesIO(converted))
    if info.samplerate != SAMPLE_RATE or info.channels != 1 or info.subtype != "PCM_16":
        converted = _python_convert(converted)
        info = sf.info(io.BytesIO(converted))
    return converted, float(info.frames) / info.samplerate


def _speech_bounds(audio: np.ndarray, sr: int, threshold_db: float = -32.0) -> tuple[int, int] | None:
    n = audio.shape[0]
    frame = max(1, sr // 100)
    if n < frame * 10:
        return None
    frames = audio[: (n // frame) * frame].reshape(-1, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    peak = rms.max()
    if peak < 1e-3:
        return None
    active = np.where(rms > max(peak * 10 ** (threshold_db / 20.0), 0.004))[0]
    if active.size == 0:
        return None
    return int(active[0]) * frame, (int(active[-1]) + 1) * frame


def _levels(audio: np.ndarray, sr: int) -> tuple[float | None, float | None]:
    """Loudness of the spoken part and of the pauses (dBFS), to compare recordings with each other."""
    frame = max(1, sr // 100)
    n = audio.shape[0]
    if n < frame * 10:
        return None, None
    frames = audio[: (n // frame) * frame].reshape(-1, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    peak = float(rms.max())
    if peak < 1e-3:
        return None, None
    speech = rms[rms > peak * 10 ** (-20 / 20.0)]
    pauses = rms[rms < peak * 10 ** (-30 / 20.0)]
    speech_db = round(float(20 * np.log10(speech.mean())), 1)
    if pauses.size < 20:  # less than 0.2 s of pauses: no reliable noise floor
        return speech_db, None
    return speech_db, round(float(20 * np.log10(pauses.mean())), 1)


def trim_edges(wav: bytes, keep_ms: int = 200, min_silence_ms: int = 300) -> tuple[bytes, float]:
    """Removes long silence at the start/end, keeping ``keep_ms`` of context around the speech."""
    data, sr = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
    audio = data[:, 0]
    n = audio.shape[0]
    bounds = _speech_bounds(audio, sr)
    if bounds is None:
        return wav, n / sr
    keep = int(sr * keep_ms / 1000)
    start = max(0, bounds[0] - keep)
    end = min(n, bounds[1] + keep)
    min_silence = int(sr * min_silence_ms / 1000)
    if start < min_silence and n - end < min_silence:
        return wav, n / sr
    out = io.BytesIO()
    sf.write(out, audio[start:end], sr, subtype="PCM_16", format="WAV")
    return out.getvalue(), (end - start) / sr


def has_speech(wav: bytes) -> bool:
    data, sr = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
    return _speech_bounds(data[:, 0], sr) is not None


def analyze(path, text: str | None = None) -> dict:
    """Waveform peaks + quality heuristics for one recording (optionally checked against its text)."""
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001
        return {"duration": 0.0, "peaks": [], "quality": {"issues": ["unreadable"]}}
    audio = data.mean(axis=1)
    n = audio.shape[0]
    duration = n / sr if sr else 0.0
    peaks: list[float] = []
    if n:
        size = max(1, n // PEAK_BUCKETS)
        usable = audio[: size * PEAK_BUCKETS]
        if usable.size:
            peaks = np.abs(usable.reshape(-1, size)).max(axis=1).round(3).tolist()
    peak = float(np.max(np.abs(audio))) if n else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if n else 0.0
    issues: list[str] = []
    bounds = _speech_bounds(audio, sr, threshold_db=-30.0) if n else None
    speech_db, noise_db = _levels(audio, sr)
    speech_seconds = 0.0
    if bounds is None:
        issues.append("silent")
    else:
        speech_seconds = (bounds[1] - bounds[0]) / sr
        if bounds[0] / sr < 0.05:
            issues.append("cut_start")
        if duration - bounds[1] / sr < 0.05:
            issues.append("cut_end")
    # one full-scale sample is just a normalised recording; real clipping flattens many samples
    if n and float(np.mean(np.abs(audio) >= 0.985)) > 0.0005:
        issues.append("clipping")
    elif peak < 0.08 and "silent" not in issues:
        issues.append("too_quiet")
    chars_per_second = None
    if text and speech_seconds > 0.3:
        letters = sum(1 for ch in text if ch.isalpha())
        chars_per_second = letters / speech_seconds
        # normal reading speed is roughly 9-20 letters per second; far outside usually means a misread or noise
        if chars_per_second < 5.0 or chars_per_second > 27.0:
            issues.append("text_mismatch")
    return {
        "duration": round(duration, 3),
        "peaks": peaks,
        "quality": {
            "peak": round(peak, 3),
            "rms_db": round(20 * np.log10(rms + 1e-9), 1),
            "speech_db": speech_db,
            "noise_db": noise_db,
            "speech_seconds": round(speech_seconds, 2),
            "chars_per_second": round(chars_per_second, 1) if chars_per_second else None,
            "issues": issues,
        },
    }
