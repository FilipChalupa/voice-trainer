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

PEAK_BUCKETS = 48


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
    # relative to the loudest frame, but never inside the room noise: a quiet take with an audible floor would
    # otherwise count as speech from the first frame to the last. The noise term is capped, so a take that is
    # speech from edge to edge (its quietest tenth is speech too) still has a spoken part.
    noise = float(np.percentile(rms, 10))
    threshold = max(peak * 10 ** (threshold_db / 20.0), min(noise * 10 ** (15 / 20.0), peak * 0.25), 0.004)
    active = np.where(rms > threshold)[0]
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


TONE_N_FFT = 2048


def speech_spectrum(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, int] | None:
    """Summed power spectrum of the louder (speech) frames of a take: (frequencies, power, number of frames)."""
    if audio.shape[0] < TONE_N_FFT:
        return None
    windows = np.lib.stride_tricks.sliding_window_view(audio, TONE_N_FFT)[:: TONE_N_FFT // 2] * np.hanning(TONE_N_FFT)
    power = np.abs(np.fft.rfft(windows, axis=1)) ** 2
    energy = power.sum(axis=1)
    speech = power[energy > np.percentile(energy, 60)]
    if not speech.shape[0]:
        return None
    return np.fft.rfftfreq(TONE_N_FFT, 1.0 / sr), speech.sum(axis=0), speech.shape[0]


def tone_db(audio: np.ndarray, sr: int) -> float | None:
    """How bass-heavy a take is: the 90-250 Hz band against the 250-1000 Hz band, in dB. Around 0 for a voice
    at a normal distance from the microphone, +3 and more when it is too close."""
    spectrum = speech_spectrum(audio, sr)
    if spectrum is None:
        return None
    freqs, power, _ = spectrum
    bass, mid = power[(freqs >= 90) & (freqs < 250)].sum(), power[(freqs >= 250) & (freqs < 1000)].sum()
    if bass <= 0 or mid <= 0:
        return None
    return round(10 * float(np.log10(bass / mid)), 1)


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
            peaks = np.abs(usable.reshape(-1, size)).max(axis=1).round(2).tolist()
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
        # a cut-off take starts or ends with loud speech, so only the loud part (-20 dB) counts here;
        # breaths and clicks near the edges must not trigger it
        loud = _speech_bounds(audio, sr, threshold_db=-20.0) or bounds
        if loud[0] / sr < 0.05:
            issues.append("cut_start")
        if duration - loud[1] / sr < 0.05:
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
            "tone_db": tone_db(audio, sr) if bounds is not None else None,
            "speech_seconds": round(speech_seconds, 2),
            "chars_per_second": round(chars_per_second, 1) if chars_per_second else None,
            "issues": issues,
        },
    }


def quiet_pauses(audio: np.ndarray, sr: int, min_pause_ms: int = 120, attenuation_db: float = 18.0, ramp_ms: int = 40, keep_ms: int = 40) -> np.ndarray:
    """Turns the room noise down inside the pauses of a take and leaves the speech untouched.

    A model trained on takes with audible pauses learns that silence hisses. Spectral denoisers also eat the
    noise-like consonants, so this only fades pauses longer than ``min_pause_ms`` down by ``attenuation_db``,
    keeping ``keep_ms`` of context around the speech and ``ramp_ms`` long fades.
    """
    frame = max(1, sr // 100)
    n = audio.shape[0]
    if n < frame * 20:
        return audio
    rms = np.sqrt((audio[: (n // frame) * frame].reshape(-1, frame) ** 2).mean(axis=1) + 1e-12)
    peak = float(rms.max())
    if peak < 1e-3:
        return audio
    noise = float(np.percentile(rms, 10))
    threshold = max(peak * 10 ** (-30 / 20.0), min(noise * 10 ** (15 / 20.0), peak * 0.25), 0.004)
    quiet = rms <= threshold
    gain = np.ones(len(rms), dtype=np.float32)
    keep, min_len = keep_ms // 10, min_pause_ms // 10
    i = 0
    while i < len(quiet):
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < len(quiet) and quiet[j]:
            j += 1
        # the edges of the take are pauses too (no speech to keep context for on the outer side)
        lo = i if i == 0 else i + keep
        hi = j if j == len(quiet) else j - keep
        if hi - lo >= min_len:
            gain[lo:hi] = 10 ** (-attenuation_db / 20.0)
        i = j
    # frame gains -> smooth per-sample envelope
    env = np.repeat(gain, frame)
    env = np.concatenate([env, np.full(n - len(env), env[-1], dtype=np.float32)]) if len(env) < n else env[:n]
    ramp = max(1, int(sr * ramp_ms / 1000))
    kernel = np.ones(ramp, dtype=np.float32) / ramp
    env = np.convolve(env, kernel, mode="same").astype(np.float32)
    return (audio * env).astype(np.float32)


MAX_LEVEL_GAIN_DB = 12.0


def processing_active(p: dict[str, float] | None) -> bool:
    return bool(p) and (p.get("highpass_hz", 0) > 0 or abs(p.get("bass_db", 0)) >= 0.1 or abs(p.get("treble_db", 0)) >= 0.1 or bool(p.get("level")))


def level_gain_db(speech_db: float | None, target_db: float | None) -> float:
    """How much to turn a take up or down so that its speech sits at the set's typical level (within reason)."""
    if speech_db is None or target_db is None:
        return 0.0
    return float(max(-MAX_LEVEL_GAIN_DB, min(MAX_LEVEL_GAIN_DB, target_db - speech_db)))


def apply_gain(audio: np.ndarray, gain_db: float) -> np.ndarray:
    if abs(gain_db) < 0.1:
        return audio
    out = audio.astype(np.float32) * np.float32(10 ** (gain_db / 20.0))
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.99:
        out *= np.float32(0.99 / peak)
    return out


def eq_gain(freqs: np.ndarray, p: dict[str, float]) -> np.ndarray:
    """Linear gain of the tone correction at each frequency: a 24 dB/octave high-pass, a bass shelf below
    ``bass_hz`` and a treble shelf above ``treble_hz`` (second order: an octave past the corner the tone is
    left alone, so a bass cut does not thin out the middle of the voice)."""
    f = np.maximum(np.asarray(freqs, dtype=np.float64), 1e-3)
    gain = np.ones_like(f)
    if p.get("highpass_hz", 0) > 0:
        gain *= 1.0 / np.sqrt(1.0 + (p["highpass_hz"] / f) ** 8)
    if abs(p.get("bass_db", 0)) >= 0.1:
        g, f0 = 10 ** (p["bass_db"] / 20.0), float(p.get("bass_hz", 250))
        gain *= np.sqrt((g * g * f0**4 + f**4) / (f0**4 + f**4))
    if abs(p.get("treble_db", 0)) >= 0.1:
        g, f0 = 10 ** (p["treble_db"] / 20.0), float(p.get("treble_hz", 4000))
        gain *= np.sqrt((f0**4 + g * g * f**4) / (f0**4 + f**4))
    return gain


def apply_processing(audio: np.ndarray, sr: int, p: dict[str, float] | None) -> np.ndarray:
    """The take with the tone correction applied. Done on the spectrum of the whole take, so the phase stays
    as it was (no smearing of consonants); a boost that would clip is scaled back."""
    if not processing_active(p) or audio.shape[0] < 16:
        return audio
    spectrum = np.fft.rfft(audio.astype(np.float64))
    out = np.fft.irfft(spectrum * eq_gain(np.fft.rfftfreq(audio.shape[0], 1.0 / sr), p), n=audio.shape[0])
    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    return out.astype(np.float32)
