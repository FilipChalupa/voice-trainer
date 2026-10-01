"""Long-lived Whisper worker: reads ``{"id", "path", "text", "language"}`` lines on stdin, answers with the
transcript and its similarity to the expected text on stdout. The model stays loaded between requests, so a
single sentence takes well under a second on the GPU."""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    text = _PUNCT.sub(" ", text)
    return text.split()


def similarity(expected: str, heard: str) -> float:
    """Word-level similarity 0..1; small typos count partially through character-level matching per word."""
    a, b = normalize(expected), normalize(heard)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def main() -> int:
    import torch
    import whisper

    model_name = os.environ.get("VT_WHISPER_MODEL", "turbo")
    root = os.environ.get("VT_WHISPER_DIR", "whisper")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(model_name, device=device, download_root=root)
    print(json.dumps({"event": "ready", "device": device}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            result = model.transcribe(req["path"], language=req.get("language") or None, fp16=(device == "cuda"), condition_on_previous_text=False, verbose=None)
            heard = " ".join(str(result.get("text", "")).split())
            print(json.dumps({"event": "result", "id": req["id"], "transcript": heard, "similarity": round(similarity(req["text"], heard), 3)}, ensure_ascii=False), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"event": "error", "id": (req or {}).get("id") if isinstance(req, dict) else None, "message": str(exc)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
