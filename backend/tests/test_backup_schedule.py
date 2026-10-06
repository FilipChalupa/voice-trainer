"""A voice in one ZIP and back, and a run planned for a set time."""
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import config, jobs
from app.main import app

client = TestClient(app)


def wav_bytes(seconds=2.0, sr=22050):
    t = np.arange(int(seconds * sr)) / sr
    audio = np.concatenate([np.zeros(sr // 3, np.float32), (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), np.zeros(sr // 3, np.float32)])
    buf = io.BytesIO()
    sf.write(buf, audio, sr, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def test_backup_holds_the_voice_and_restores_as_a_new_one():
    client.post("/api/voices", json={"name": "Záloha", "owner": "Test Person", "language": "cs"})
    original = config.current_voice()
    client.put("/api/voice", json={"lexicon": {"Turris": "turis"}, "processing": {"bass_db": -3}})
    rec = client.post("/api/recordings", data={"text": "Věta do zálohy."}, files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    job_dir = original.jobs_dir / "20260104_000000_bak"
    for sub in ("export", "checkpoints", "cache", "dataset"):
        (job_dir / sub).mkdir(parents=True)
    (job_dir / "export" / "cs_CZ-z-medium.onnx").write_bytes(b"onnx")
    (job_dir / "checkpoints" / "last.ckpt").write_bytes(b"x" * 100)
    (job_dir / "cache" / "big.pt").write_bytes(b"x" * 100)
    (job_dir / "job.json").write_text(json.dumps({"job_id": job_dir.name, "voice_id": original.id}))

    res = client.get("/api/backup")
    assert res.status_code == 200 and res.headers["content-disposition"].endswith('voice-zaloha.zip"')
    names = set(zipfile.ZipFile(io.BytesIO(res.content)).namelist())
    assert {"backup.json", "voice.json", f"recordings/{rec['id']}.wav", "recordings/recordings.json", f"jobs/{job_dir.name}/export/cs_CZ-z-medium.onnx", f"jobs/{job_dir.name}/job.json"} <= names
    assert not any("checkpoints" in n or "cache" in n or "dataset" in n for n in names)

    restored = client.post("/api/backup/restore", files={"file": ("voice.zip", res.content, "application/zip")}).json()
    assert restored["voice_id"] != original.id and restored["name"] == "Záloha" and restored["files"] >= 5
    copy = config.current_voice()
    assert copy.id == restored["voice_id"]
    settings = client.get("/api/voices").json()["voice"]
    assert settings["lexicon"] == {"Turris": "turis"} and settings["processing"]["bass_db"] == -3
    items = client.get("/api/recordings").json()["items"]
    assert [r["text"] for r in items] == ["Věta do zálohy."]
    assert client.get("/api/jobs").json()["items"][0]["job_id"] == job_dir.name

    # not a backup, or a path that climbs out: refused before anything is written
    assert client.post("/api/backup/restore", files={"file": ("x.zip", b"nope", "application/zip")}).status_code == 400
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("backup.json", json.dumps({"app": "voice-trainer", "voice_id": "evil"}))
        zf.writestr("../../escape.txt", "x")
    assert client.post("/api/backup/restore", files={"file": ("x.zip", evil.getvalue(), "application/zip")}).json()["detail"]["code"] == "bad_backup"
    for vid in (copy.id, original.id):
        client.delete(f"/api/voices/{vid}")


def test_scheduled_training_starts_when_due(monkeypatch, tmp_path):
    client.post("/api/voices", json={"name": "Plán", "owner": "Test Person", "language": "cs"})
    monkeypatch.setattr(jobs, "SCHEDULE_FILE", tmp_path / "schedule.json")
    assert client.get("/api/train/schedule").json() == {}
    assert client.post("/api/train/schedule", json={"at": "yesterday"}).status_code == 400
    assert client.post("/api/train/schedule", json={"at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}).status_code == 400
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    state = client.post("/api/train/schedule", json={"at": soon, "from_job": "20260101_000000_abc"}).json()
    assert state["voice_id"] == config.current_voice().id and state["from_job"] == "20260101_000000_abc"
    assert client.get("/api/train/schedule").json()["at"] == state["at"]

    # the watcher's one step: not due yet, nothing happens; due, the run starts (here: fails for a reason the person sees)
    started = []
    monkeypatch.setattr(jobs.manager, "start", lambda from_job=None: started.append(from_job))
    import pytest

    (tmp_path / "schedule.json").write_text(json.dumps({**state, "at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()}))

    class Stop(Exception):
        pass

    calls = {"n": 0}

    def fake_sleep(s):
        calls["n"] += 1
        if calls["n"] > 1:
            raise Stop()

    monkeypatch.setattr(jobs.time, "sleep", fake_sleep)
    with pytest.raises(Stop):
        jobs.manager._watch_schedule()
    assert started == ["20260101_000000_abc"] and not (tmp_path / "schedule.json").exists()

    # another voice selected when the time comes: the plan is dropped with the reason
    (tmp_path / "schedule.json").write_text(json.dumps({**state, "voice_id": "someone-else", "at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()}))
    calls["n"] = 0
    with pytest.raises(Stop):
        jobs.manager._watch_schedule()
    left = json.loads((tmp_path / "schedule.json").read_text())
    assert left["at"] is None and left["code"] == "other_voice" and started == ["20260101_000000_abc"]
    assert client.delete("/api/train/schedule").status_code == 200 and client.get("/api/train/schedule").json() == {}
    client.delete(f"/api/voices/{config.current_voice().id}")
