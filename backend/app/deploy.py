"""Deploy to the server: the trained voice and the pronunciation dictionary go to the machine Piper runs on.

The app has its own SSH key. On the server that key is allowed to run exactly one thing, a small receiver
script (see `receiver_script`): it takes a tar archive, stores voice files and the dictionary into one
directory and restarts Piper. Where to store and how to restart is written into the script on the server, not
sent by the app, so whoever reaches this app cannot run anything else there.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import tarfile
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .config import DATA_DIR, Voice
from .runs import find_job_dir, list_exports, read_json

router = APIRouter(prefix="/api", tags=["deploy"])

DEPLOY_FILE = DATA_DIR / "deploy.json"
LAST_FILE = DATA_DIR / "deploy-last.json"  # which run is on the server now
SSH_DIR = DATA_DIR / "ssh"
RECEIVER_PATH = "/usr/local/bin/voice-trainer-deploy"
DEFAULTS: dict[str, Any] = {"host": "", "user": "root", "port": 22, "directory": "/opt/piper-data", "restart": "docker restart wyoming-piper"}
_lock = threading.Lock()


def load() -> dict[str, Any]:
    settings = dict(DEFAULTS)
    try:
        settings.update({k: v for k, v in json.loads(DEPLOY_FILE.read_text()).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return settings


def save(update: dict[str, Any]) -> dict[str, Any]:
    settings = load()
    host = str(update.get("host", settings["host"])).strip()
    user = str(update.get("user", settings["user"])).strip()
    directory = str(update.get("directory", settings["directory"])).strip().rstrip("/") or "/"
    restart = " ".join(str(update.get("restart", settings["restart"])).split())
    try:
        port = int(update.get("port", settings["port"]))
    except (TypeError, ValueError):
        port = 0
    if host and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}", host):
        raise HTTPException(400, {"code": "bad_host", "message": "The server address may hold letters, digits, dots and dashes only"})
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise HTTPException(400, {"code": "bad_user", "message": "Bad user name"})
    if not 1 <= port <= 65535:
        raise HTTPException(400, {"code": "bad_port", "message": "Bad port"})
    if not re.fullmatch(r"/[A-Za-z0-9._/-]*", directory) or ".." in directory:
        raise HTTPException(400, {"code": "bad_directory", "message": "The directory must be an absolute path of plain characters"})
    if len(restart) > 300:
        raise HTTPException(400, {"code": "bad_restart", "message": "The restart command is too long"})
    settings = {"host": host, "user": user, "port": port, "directory": directory, "restart": restart}
    with _lock:
        DEPLOY_FILE.write_text(json.dumps(settings, indent=2))
    return settings


def public_key() -> str:
    """The app's own key pair, made on first use."""
    key = SSH_DIR / "id_ed25519"
    with _lock:
        if not key.exists():
            SSH_DIR.mkdir(parents=True, exist_ok=True)
            SSH_DIR.chmod(0o700)
            proc = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "voice-trainer deploy", "-f", str(key)], capture_output=True, text=True)
            if proc.returncode != 0:
                raise HTTPException(500, {"code": "no_ssh", "message": f"Could not create an SSH key: {proc.stderr.strip()[:200]}"})
    return Path(str(key) + ".pub").read_text().strip()


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def receiver_script(settings: dict[str, Any]) -> str:
    """The script for the server. `ping` answers, `deploy` reads a tar archive from standard input."""
    return f"""#!/bin/sh
# Receiver for voice-trainer's "deploy to the server": the only thing its SSH key may run here.
# Takes a tar archive on standard input, stores voice files and the pronunciation dictionary, restarts Piper.
set -eu
DIR={_quote(settings["directory"])}
RESTART={_quote(settings["restart"])}
case "${{SSH_ORIGINAL_COMMAND:-}}" in
  ping) echo "voice-trainer receiver ready: $DIR"; exit 0 ;;
  deploy) ;;
  *) echo "unknown command" >&2; exit 2 ;;
esac
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar -x -f - -C "$tmp" --no-same-owner --no-same-permissions
for f in "$tmp"/* "$tmp"/.[!.]*; do
  [ -e "$f" ] || [ -L "$f" ] || continue
  name=$(basename "$f")
  if [ -L "$f" ] || [ ! -f "$f" ]; then echo "refused: $name is not a plain file" >&2; exit 2; fi
  case "$name" in
    *.onnx|*.onnx.json|cs_dict) ;;
    *) echo "refused: $name" >&2; exit 2 ;;
  esac
done
mkdir -p "$DIR"
for f in "$tmp"/*; do
  [ -f "$f" ] || continue
  name=$(basename "$f")
  # written in place: a file mounted into a container keeps pointing at the old one when it is replaced
  cat "$f" > "$DIR/$name"
  echo "stored $name"
done
sh -c "$RESTART"
echo "restarted"
"""


def setup_commands(settings: dict[str, Any], key: str) -> str:
    """What to run once on the server (as the user the app connects as)."""
    return (
        f"cat > {RECEIVER_PATH} <<'VOICE_TRAINER_EOF'\n{receiver_script(settings)}VOICE_TRAINER_EOF\n"
        f"chmod 755 {RECEIVER_PATH}\n"
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh\n"
        f"echo 'command=\"{RECEIVER_PATH}\",restrict {key}' >> ~/.ssh/authorized_keys\n"
    )


def run_ssh(settings: dict[str, Any], command: str, data: bytes = b"", timeout: int = 300) -> tuple[bool, str]:
    if not settings["host"]:
        raise HTTPException(400, {"code": "not_configured", "message": "Set the server address first"})
    public_key()
    cmd = [
        "ssh", "-i", str(SSH_DIR / "id_ed25519"), "-p", str(settings["port"]),
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={SSH_DIR / 'known_hosts'}", "-o", "ConnectTimeout=10",
        f"{settings['user']}@{settings['host']}", command,
    ]
    try:
        proc = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise HTTPException(500, {"code": "no_ssh", "message": "The ssh client is not installed"}) from exc
    except subprocess.TimeoutExpired:
        return False, "The server did not answer in time."
    output = (proc.stdout.decode(errors="replace") + proc.stderr.decode(errors="replace")).strip()
    return proc.returncode == 0, output[-2000:]


def archive(job_id: str, file: str | None = None) -> tuple[bytes, list[str]]:
    """The chosen variant under the voice's plain name, with its config and, for Czech, the dictionary."""
    from .synth import espeak_dictionary

    job_dir = find_job_dir(job_id)
    job = read_json(job_dir / "job.json")
    exports = list_exports(job_dir, job_id)
    if not exports:
        raise HTTPException(409, {"code": "no_models", "message": "This run has no exported voice yet"})
    main = next((e for e in exports if e["variant"] == "last"), exports[0])
    chosen = next((e for e in exports if e["file"] == file), None) or main
    name = main["file"][: -len(".onnx")]
    model = job_dir / "export" / chosen["file"]
    config = Path(str(model) + ".json")
    if not config.exists():
        raise HTTPException(409, {"code": "no_models", "message": "The voice has no configuration file"})
    members = [(model, f"{name}.onnx"), (config, f"{name}.onnx.json")]
    dictionary = espeak_dictionary(Voice(job.get("voice_id") or ""))
    if dictionary is not None:
        members.append((dictionary, "cs_dict"))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path, arcname in members:
            info = tar.gettarinfo(str(path), arcname=arcname)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with path.open("rb") as fh:
                tar.addfile(info, fh)
    return buffer.getvalue(), [arcname for _, arcname in members]


def describe() -> dict[str, Any]:
    settings = load()
    try:
        key = public_key()
    except HTTPException:
        key = ""
    return {"settings": settings, "configured": bool(settings["host"]), "public_key": key, "setup": setup_commands(settings, key) if key else "", "receiver": RECEIVER_PATH}


@router.get("/deploy")
def get_deploy() -> dict[str, Any]:
    return describe()


@router.put("/deploy")
def put_deploy(body: dict[str, Any]) -> dict[str, Any]:
    save(body)
    return describe()


@router.post("/deploy/test")
def post_deploy_test() -> dict[str, Any]:
    ok, output = run_ssh(load(), "ping", timeout=30)
    return {"ok": ok and "receiver ready" in output, "output": output}


@router.post("/jobs/{job_id}/deploy")
def post_deploy(job_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from .config import now

    settings = load()
    file = str((body or {}).get("file") or "") or None
    data, files = archive(job_id, file)
    ok, output = run_ssh(settings, "deploy", data)
    ok = ok and "restarted" in output
    if ok:
        with _lock:
            LAST_FILE.write_text(json.dumps({"job_id": job_id, "file": file or files[0], "host": settings["host"], "at": now()}, indent=2))
    return {"ok": ok, "output": output, "files": files}
