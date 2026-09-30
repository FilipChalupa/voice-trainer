"""The transcription import and the model check, with the heavy workers replaced by small stand-ins."""
import io
import json
import time

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import check, config, importer
from app.main import app

client = TestClient(app)


def wav_bytes(seconds=2.0, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    audio = np.concatenate([np.zeros(sr // 4, np.float32), (0.4 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), np.zeros(sr // 4, np.float32)])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


FAKE_TRANSCRIBE = '''
import json, shutil, sys
from pathlib import Path
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
out = Path(args["--out-dir"]); (out / "clips").mkdir(exist_ok=True)
print("@@" + json.dumps({"event": "stage", "stage": "transcribing", "seconds": 2.5, "device": "cpu"}), flush=True)
print(" 50%|#####     | 1/2", end="\\r", flush=True)
clips = []
for i, text in enumerate(["První věta z nahrávky.", "Druhá věta z nahrávky."], start=1):
    shutil.copy(args["--input"], out / "clips" / f"{i:04d}.wav")
    clips.append({"file": f"{i:04d}.wav", "text": text, "start": 0, "end": 2.5})
(out / "clips.json").write_text(json.dumps(clips, ensure_ascii=False))
print("@@" + json.dumps({"event": "done", "clips": 2, "seconds": 2.5}), flush=True)
'''


def wait_for(fn, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = fn()
        if state["status"] not in ("running", "loading", "transcribing", "cutting", "storing", "downloading"):
            return state
        time.sleep(0.1)
    raise AssertionError(f"still running: {state}")


def setup_module():
    if config.current_voice() is None:
        client.post("/api/voices", json={"name": "Worker", "owner": "Test Person", "language": "cs"})


def test_transcribe_import_stores_sentences(monkeypatch, tmp_path):
    script = tmp_path / "fake_transcribe.py"
    script.write_text(FAKE_TRANSCRIBE)
    monkeypatch.setattr(importer, "transcribe_command", lambda source, work, language: [importer.sys.executable, str(script), "--input", str(source), "--out-dir", str(work)])
    before = client.get("/api/recordings").json()["count"]
    res = client.post("/api/transcribe", files={"file": ("reading.wav", wav_bytes(), "audio/wav")})
    assert res.status_code == 200 and res.json()["status"] in ("loading", "transcribing", "storing", "done")
    state = wait_for(lambda: client.get("/api/transcribe").json())
    assert state["status"] == "done", state
    assert state["result"]["stored"] == 2 and state["result"]["count"] == before + 2
    assert any("2 sentences" in line for line in state["log"])
    items = client.get("/api/recordings").json()["items"]
    transcribed = [r for r in items if r["source"] == "transcribed"]
    assert sorted(r["text"] for r in transcribed) == ["Druhá věta z nahrávky.", "První věta z nahrávky."]
    assert not (config.current_voice().dir / "imports").exists()
    # unsupported file types and a second import while one runs are refused
    assert client.post("/api/transcribe", files={"file": ("x.txt", b"hi", "text/plain")}).json()["detail"]["code"] == "bad_audio"


def test_model_check_flags_the_odd_recording(monkeypatch):
    voice = config.current_voice()
    items = client.get("/api/recordings").json()["items"]
    assert len(items) >= 2
    job_dir = voice.jobs_dir / "20260101_000000_chk"
    (job_dir / "export").mkdir(parents=True)
    (job_dir / "export" / "cs_CZ-w-medium.onnx").write_bytes(b"onnx")
    (job_dir / "export" / "exports.json").write_text(json.dumps([{"variant": "last", "file": "cs_CZ-w-medium.onnx", "checkpoint": "last.ckpt", "size": 4}]))
    (job_dir / "job.json").write_text(json.dumps({"job_id": job_dir.name, "voice_id": voice.id, "slug": "w", "max_epochs": 10, "training": {}}))
    (job_dir / "result.json").write_text(json.dumps({"status": "done", "epoch": 10}))

    # no real voice: synthesis returns a tone, and the distance is large only for the take made 3 s long
    odd = items[0]["id"]
    sf.write(str(voice.recordings_dir / f"{odd}.wav"), np.zeros(22050 * 3, np.float32), 22050, subtype="PCM_16")
    monkeypatch.setattr("app.synth.load_voice", lambda path: None)
    monkeypatch.setattr("app.synth.synthesize", lambda path, text, *scales: wav_bytes(seconds=1.0))
    monkeypatch.setattr(check, "mel_distance", lambda ref, synth, sr: 0.5 if len(ref) == 22050 * 3 else 0.01)

    assert client.post(f"/api/jobs/{job_dir.name}/check").json()["status"] == "running"
    state = wait_for(lambda: client.get(f"/api/jobs/{job_dir.name}/check").json())
    assert state["status"] == "done", state
    result = state["result"]
    assert result["count"] == len(items) and result["items"][0]["id"] == odd and result["items"][0]["flagged"] is True
    assert result["flagged"] >= 1
    assert client.get(f"/api/jobs/{job_dir.name}/check/audio/{odd}").status_code == 200
    flagged = [r["id"] for r in client.get("/api/recordings").json()["items"] if "model_mismatch" in r["quality"]["issues"]]
    assert flagged == [odd]
    # once the run is gone, the verdicts no longer apply
    client.delete(f"/api/jobs/{job_dir.name}")
    assert all("model_mismatch" not in r["quality"]["issues"] for r in client.get("/api/recordings").json()["items"])
    for r in items:
        client.delete(f"/api/recordings/{r['id']}")
