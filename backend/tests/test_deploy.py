import io
import json
import shutil
import subprocess
import tarfile

import pytest
from fastapi.testclient import TestClient

from app import config, deploy
from app.main import app

client = TestClient(app)


def run_receiver(tmp_path, command, data=b""):
    """The server-side script, run the way sshd would run it for the app's key."""
    target = tmp_path / "piper-data"
    script = tmp_path / "receiver.sh"
    script.write_text(deploy.receiver_script({"directory": str(target), "restart": f"echo \"it's restarted\" > {tmp_path / 'restarted'}"}))
    proc = subprocess.run(["sh", str(script)], input=data, capture_output=True, env={"PATH": "/usr/bin:/bin", "SSH_ORIGINAL_COMMAND": command})
    return proc, target


def tar_of(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            if content is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            else:
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_receiver_stores_voice_files_in_place_and_restarts(tmp_path):
    proc, target = run_receiver(tmp_path, "ping")
    assert proc.returncode == 0 and b"receiver ready" in proc.stdout and not target.exists()
    target.mkdir()
    (target / "cs_dict").write_bytes(b"old")
    inode = (target / "cs_dict").stat().st_ino
    proc, _ = run_receiver(tmp_path, "deploy", tar_of({"cs_CZ-a-medium.onnx": b"model", "cs_CZ-a-medium.onnx.json": b"{}", "cs_dict": b"new dictionary"}))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.decode().split("\n")[-2] == "restarted" and (tmp_path / "restarted").read_text().strip() == "it's restarted"
    assert (target / "cs_CZ-a-medium.onnx").read_bytes() == b"model" and (target / "cs_dict").read_bytes() == b"new dictionary"
    assert (target / "cs_dict").stat().st_ino == inode  # the same file: a container that has it mounted sees the new content


@pytest.mark.parametrize("command,members", [
    ("deploy", {"evil.sh": b"x"}),
    ("deploy", {"cs_CZ-a-medium.onnx": b"m", "authorized_keys": b"k"}),
    ("deploy", {"sub/cs_dict": b"x"}),
    ("deploy", {"cs_dict": None}),  # a symbolic link
    ("deploy", {".hidden.onnx.bak": b"x"}),
    ("rm -rf /", {"cs_dict": b"x"}),
    ("", {"cs_dict": b"x"}),
])
def test_receiver_refuses_anything_but_voice_files(tmp_path, command, members):
    proc, target = run_receiver(tmp_path, command, tar_of(members))
    assert proc.returncode != 0
    assert not (tmp_path / "restarted").exists() and not list(target.glob("*")) if target.exists() else True


def test_settings_are_validated_and_the_setup_names_the_restricted_key(monkeypatch, tmp_path):
    if shutil.which("ssh-keygen") is None:
        pytest.skip("no ssh client here")
    monkeypatch.setattr(deploy, "DEPLOY_FILE", tmp_path / "deploy.json")
    monkeypatch.setattr(deploy, "SSH_DIR", tmp_path / "ssh")
    first = client.get("/api/deploy").json()
    assert first["configured"] is False and first["public_key"].startswith("ssh-ed25519 ") and first["settings"]["port"] == 22
    for bad in ({"host": "a b"}, {"host": "x; rm"}, {"user": "Root!"}, {"port": 0}, {"directory": "relative"}, {"directory": "/a/../b"}, {"directory": "/a b"}):
        assert client.put("/api/deploy", json=bad).status_code == 400, bad
    saved = client.put("/api/deploy", json={"host": "10.0.0.5", "directory": "/opt/ai-stack/piper-data/", "restart": "cd /opt/ai-stack && docker compose restart piper"}).json()
    assert saved["configured"] and saved["settings"]["directory"] == "/opt/ai-stack/piper-data"
    setup = saved["setup"]
    assert f'command="{deploy.RECEIVER_PATH}",restrict {saved["public_key"]}' in setup
    assert "DIR='/opt/ai-stack/piper-data'" in setup and "docker compose restart piper" in setup
    assert client.get("/api/deploy").json()["public_key"] == first["public_key"]  # the key is made once


def test_deploy_sends_the_chosen_variant_under_the_plain_name(monkeypatch, tmp_path):
    monkeypatch.setattr(deploy, "DEPLOY_FILE", tmp_path / "deploy.json")
    monkeypatch.setattr(deploy, "SSH_DIR", tmp_path / "ssh")
    monkeypatch.setattr(deploy, "public_key", lambda: "ssh-ed25519 AAAA test")
    if config.current_voice() is None:
        client.post("/api/voices", json={"name": "Deploy", "owner": "Test Person", "language": "cs"})
    voice = config.current_voice()
    job_dir = voice.jobs_dir / "20260103_000000_dep"
    (job_dir / "export").mkdir(parents=True)
    for name, content in (("cs_CZ-w-medium.onnx", b"last"), ("cs_CZ-w-medium.best_mel.onnx", b"best")):
        (job_dir / "export" / name).write_bytes(content)
        (job_dir / "export" / f"{name}.json").write_text(json.dumps({"variant": content.decode()}))
    (job_dir / "export" / "exports.json").write_text(json.dumps([{"variant": "last", "file": "cs_CZ-w-medium.onnx"}, {"variant": "best_mel", "file": "cs_CZ-w-medium.best_mel.onnx"}]))
    (job_dir / "job.json").write_text(json.dumps({"job_id": job_dir.name, "voice_id": voice.id, "slug": "w", "language": "cs"}))
    monkeypatch.setattr("app.synth.espeak_dictionary", lambda voice: None)

    assert client.post(f"/api/jobs/{job_dir.name}/deploy").json()["detail"]["code"] == "not_configured"
    client.put("/api/deploy", json={"host": "server.lan"})
    calls = []

    def fake_run(cmd, input=b"", capture_output=True, timeout=0):
        calls.append((cmd, input))
        return subprocess.CompletedProcess(cmd, 0, b"stored cs_CZ-w-medium.onnx\nrestarted\n", b"")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    res = client.post(f"/api/jobs/{job_dir.name}/deploy", json={"file": "cs_CZ-w-medium.best_mel.onnx"}).json()
    assert res["ok"] is True and res["files"] == ["cs_CZ-w-medium.onnx", "cs_CZ-w-medium.onnx.json"]
    cmd, data = calls[-1]
    assert cmd[0] == "ssh" and cmd[-2:] == ["root@server.lan", "deploy"] and "BatchMode=yes" in cmd
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert tar.getnames() == ["cs_CZ-w-medium.onnx", "cs_CZ-w-medium.onnx.json"]
        assert tar.extractfile("cs_CZ-w-medium.onnx").read() == b"best"
    assert client.post("/api/deploy/test").json() == {"ok": False, "output": "stored cs_CZ-w-medium.onnx\nrestarted"}
    client.delete(f"/api/jobs/{job_dir.name}")
