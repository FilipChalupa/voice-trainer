"""Cuts a long recording into sentences with a Whisper transcript (runs as a subprocess of the API).

Progress goes to stdout as ``@@{json}`` lines like the trainer; the result is ``clips/NNNN.wav`` plus
``clips.json`` in the output directory. The clips are handed to the normal recording pipeline afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 22050
MAX_CLIP_SECONDS = 14.0  # longer sentences are split at a pause
MIN_CLIP_SECONDS = 0.8
SPLIT_GAP_SECONDS = 0.9  # a pause this long ends a sentence even without punctuation
SEARCH_SECONDS = 0.6  # how far around Whisper's word boundary the quietest point is looked for
FRAME = SAMPLE_RATE // 100
SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)]*$")


def emit(event: str, **data) -> None:
    print("@@" + json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def load_audio(path: Path) -> np.ndarray:
    """The recording as 22.05 kHz mono float32, decoded by ffmpeg (any container/codec)."""
    import subprocess

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def words_of(result: dict) -> list[dict]:
    words = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            text = str(w.get("word", ""))  # keeps its leading space, so joining the words keeps hyphens tight
            if text.strip():
                words.append({"text": text, "start": float(w["start"]), "end": float(w["end"])})
    return words


def sentences_of(words: list[dict]) -> list[dict]:
    """Groups words into sentences: at sentence punctuation, at long pauses, or when a clip gets too long."""
    out: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        if current:
            out.append({"text": " ".join("".join(w["text"] for w in current).split()), "start": current[0]["start"], "end": current[-1]["end"]})
            current.clear()

    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 0.0
        length = w["end"] - current[0]["start"]
        if SENTENCE_END.search(w["text"].strip()) or gap >= SPLIT_GAP_SECONDS or (length >= MAX_CLIP_SECONDS and gap >= 0.25):
            flush()
    flush()
    return out


def frame_rms(audio: np.ndarray) -> np.ndarray:
    frames = audio[: (len(audio) // FRAME) * FRAME].reshape(-1, FRAME)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-12)


def quietest_point(rms: np.ndarray, lo: float, hi: float) -> float:
    """Middle of the quietest 120 ms inside [lo, hi] seconds: the best place to cut between two sentences."""
    a, b = max(0, int(lo * 100)), min(len(rms), int(hi * 100))
    if b - a < 12:
        return (lo + hi) / 2
    window = np.convolve(rms[a:b], np.ones(12) / 12, mode="valid")
    return (a + int(np.argmin(window)) + 6) / 100


def cut_points(rms: np.ndarray, sentences: list[dict], total: float) -> list[tuple[float, float]]:
    """Whisper's word times are rough; every cut is moved to the quietest moment near the boundary."""
    bounds = []
    for i, s in enumerate(sentences):
        if i == 0:
            start = quietest_point(rms, max(0.0, s["start"] - SEARCH_SECONDS), min(s["start"] + 0.2, s["end"]))
        else:
            start = bounds[-1][1]
        if i + 1 < len(sentences):
            nxt = sentences[i + 1]
            end = quietest_point(rms, max(s["end"] - SEARCH_SECONDS, start + 0.3), min(nxt["start"] + SEARCH_SECONDS, nxt["end"]))
        else:
            end = quietest_point(rms, max(s["end"] - 0.2, start + 0.3), min(s["end"] + SEARCH_SECONDS, total))
        bounds.append((start, end))
    return bounds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--language", default="cs")
    parser.add_argument("--model", default=os.environ.get("VT_WHISPER_MODEL", "turbo"))
    parser.add_argument("--download-root", default=os.environ.get("VT_WHISPER_DIR", "whisper"))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    import torch
    import whisper

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_file = Path(args.download_root) / os.path.basename(whisper._MODELS.get(args.model, f"{args.model}.pt"))
    emit("stage", stage="downloading" if not model_file.exists() else "loading", model=args.model, device=device)
    model = whisper.load_model(args.model, device=device, download_root=args.download_root)

    audio = load_audio(Path(args.input))
    total = len(audio) / SAMPLE_RATE
    emit("stage", stage="transcribing", seconds=round(total, 1), device=device)
    # whisper works on 16 kHz; it resamples/decodes itself from the file
    result = model.transcribe(str(args.input), language=args.language, word_timestamps=True, condition_on_previous_text=False, fp16=(device == "cuda"), verbose=False)
    del model
    if device == "cuda":
        torch.cuda.empty_cache()

    sentences = sentences_of(words_of(result))
    emit("stage", stage="cutting", sentences=len(sentences))
    clips = []
    rms = frame_rms(audio)
    for s, (start, end) in zip(sentences, cut_points(rms, sentences, total)):
        if end - start < MIN_CLIP_SECONDS or len(s["text"]) < 3:
            continue
        name = f"{len(clips) + 1:04d}.wav"
        sf.write(str(clips_dir / name), audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)], SAMPLE_RATE, subtype="PCM_16")
        clips.append({"file": name, "text": s["text"], "start": round(start, 2), "end": round(end, 2)})
    (out_dir / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1))
    emit("done", clips=len(clips), seconds=round(total, 1), language=result.get("language"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        emit("error", message=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
