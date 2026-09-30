"""Fills the current voice of a running instance with synthetic recordings, for tests and screenshots.

Runs inside the container (it needs Piper): the released Czech voice reads the prompt sentences and the results are
uploaded through the public API as if a person had read them, consent included. Never point it at an instance
that holds a real voice you care about.

    docker compose -p vt-test exec app python /app/scripts/demo_dataset.py 150
"""
import io
import os
import sys
import time
import wave

import numpy as np
import requests
from piper import PiperVoice

API = os.environ.get("API", "http://127.0.0.1:8000")
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/cs/cs_CZ/jirka/medium/cs_CZ-jirka-medium.onnx"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 100
MODEL = "/tmp/demo-voice.onnx"

for suffix in ([] if os.path.exists(MODEL + ".json") else ["", ".json"]):
    r = requests.get(HF + suffix, timeout=300)
    r.raise_for_status()
    open(MODEL + suffix, "wb").write(r.content)
voice = PiperVoice.load(MODEL)


def tts(text: str) -> bytes:
    """A sentence at 60 % level with a little silence around it, like a real take."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voice.synthesize_wav(text, w)
    buf.seek(0)
    with wave.open(buf) as r:
        rate = r.getframerate()
        audio = np.frombuffer(r.readframes(r.getnframes()), dtype=np.int16).astype(np.float32) * 0.6
    pad = np.zeros(int(rate * 0.35), dtype=np.float32)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.concatenate([pad, audio, pad]).astype(np.int16).tobytes())
    return out.getvalue()


# wait for the downloaded corpus to replace the built-in set (skipped when offline)
for _ in range(60):
    p = requests.get(f"{API}/api/prompts?count=1").json()
    if p["source"] == "corpus" or (p.get("preparing") or {}).get("state") == "error" or os.environ.get("VT_OFFLINE"):
        break
    time.sleep(2)
print("prompt source:", p["source"], "total:", p["total"])

info = requests.get(f"{API}/api/voices").json()["voice"]
if not info["has_consent"]:
    res = requests.post(f"{API}/api/consent", files={"file": ("c.wav", tts(info["consent_statement"]), "audio/wav")})
    print("consent:", res.status_code)

done = 0
while done < COUNT:
    items = requests.get(f"{API}/api/prompts?count=20").json()["items"]
    if not items:
        break
    for item in items:
        r = requests.post(f"{API}/api/recordings", data={"text": item["text"], "prompt_id": item["id"]}, files={"file": ("a.wav", tts(item["text"]), "audio/wav")})
        if r.status_code != 200:
            print("upload failed:", r.status_code, r.text[:200])
            requests.post(f"{API}/api/prompts/{item['id']}/skip")
            continue
        done += 1
        if done >= COUNT:
            break
rec = requests.get(f"{API}/api/recordings").json()
print("recordings:", rec["count"], "minutes:", rec["minutes"])
