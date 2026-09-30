"""Training job manager: fine-tunes a Piper voice in a subprocess, parses its progress, streams it via SSE."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from . import base
from .config import KEEP_JOBS, LANGUAGES, MIN_MINUTES, SAMPLE_RATE, VOICES_DIR, Voice, current_voice, list_voices, load_settings, now, slugify
from .recordings import list_recordings, total_minutes
from .voices import has_consent, require_voice

PROGRESS_BAR = re.compile(r"^\s*\d{1,3}%\|")

router = APIRouter(prefix="/api", tags=["training"])

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MAX_LOG_LINES = 600
RUNNING = ("downloading", "preparing", "training", "exporting")
FINISHED = ("done", "failed", "cancelled")
SAFE = re.compile(r"^[A-Za-z0-9_.\-=]+$")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def find_job_dir(job_id: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_\-]+$", job_id or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad job id"})
    for entry in list_voices():
        candidate = VOICES_DIR / entry["id"] / "jobs" / job_id
        if candidate.is_dir():
            return candidate
    raise HTTPException(404, {"code": "not_found", "message": "Job not found"})


def list_previews(job_dir: Path, job_id: str) -> list[dict[str, Any]]:
    out = []
    preview_root = job_dir / "previews"
    if not preview_root.is_dir():
        return out
    for d in sorted(preview_root.iterdir()):
        if not d.is_dir() or not d.name.startswith("epoch_"):
            continue
        sentences = _read_json(d / "sentences.json") if (d / "sentences.json").exists() else []
        files = sorted(d.glob("*.wav"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
        out.append({
            "epoch": int(d.name.split("_")[1]),
            "items": [{"url": f"/api/jobs/{job_id}/previews/{d.name}/{f.name}", "text": sentences[int(f.stem)] if isinstance(sentences, list) and f.stem.isdigit() and int(f.stem) < len(sentences) else ""} for f in files],
        })
    return out


def list_exports(job_dir: Path, job_id: str) -> list[dict[str, Any]]:
    exports = _read_json(job_dir / "export" / "exports.json") if (job_dir / "export" / "exports.json").exists() else []
    out = []
    for e in exports if isinstance(exports, list) else []:
        if (job_dir / "export" / e["file"]).exists():
            out.append({**e, "url": f"/api/jobs/{job_id}/export/{e['file']}", "config_url": f"/api/jobs/{job_id}/export/{e['file']}.json"})
    return out


def job_summary(job_dir: Path, running_job_id: str | None) -> dict[str, Any] | None:
    job = _read_json(job_dir / "job.json")
    if not job:
        return None
    result = _read_json(job_dir / "result.json")
    status = result.get("status")
    if status is None:
        status = "running" if running_job_id == job["job_id"] else "interrupted"
    has_last = (job_dir / "checkpoints" / "last.ckpt").exists()
    exports = list_exports(job_dir, job["job_id"])
    return {
        "job_id": job["job_id"],
        "voice_id": job.get("voice_id"),
        "name": job.get("name"),
        "slug": job.get("slug"),
        "language": job.get("language"),
        "created_at": job.get("created_at"),
        "finished_at": result.get("finished_at"),
        "status": status,
        "minutes": job.get("minutes"),
        "recordings": job.get("recordings"),
        "training": job.get("training"),
        "max_epochs": job.get("max_epochs"),
        "epoch": result.get("epoch"),
        "validation_last": (result.get("validation") or [None])[-1],
        "exports": exports,
        "bundle_url": f"/api/jobs/{job['job_id']}/bundle" if exports else None,
        "resumable": has_last and status in ("interrupted", "cancelled", "failed", "done"),
        "previews": len(list_previews(job_dir, job["job_id"])),
    }


def list_jobs(voice: Voice, running_job_id: str | None = None) -> list[dict[str, Any]]:
    voice.ensure()
    running = running_job_id
    if running is None:
        mgr = globals().get("manager")
        if mgr is not None and mgr.is_running():
            running = mgr.state.get("job_id")
    jobs = []
    for job_dir in sorted(voice.jobs_dir.iterdir(), reverse=True):
        if job_dir.is_dir():
            summary = job_summary(job_dir, running)
            if summary:
                jobs.append(summary)
    return jobs


def prune_jobs(voice: Voice, keep: int = KEEP_JOBS) -> int:
    finished = [j for j in list_jobs(voice) if j["status"] in FINISHED]
    removed = 0
    for job in finished[keep:]:
        shutil.rmtree(voice.jobs_dir / job["job_id"], ignore_errors=True)
        removed += 1
    return removed


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self.state: dict[str, Any] = self._idle_state()
        self.log: deque[str] = deque(maxlen=MAX_LOG_LINES)
        try:
            self.load_voice_state(current_voice())
        except Exception:  # noqa: BLE001  (best effort only)
            pass

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "status": "idle",  # idle | downloading | preparing | training | exporting | done | failed | cancelled | interrupted
            "job_id": None,
            "voice_id": None,
            "name": None,
            "stage_key": None,
            "message": None,
            "message_key": None,
            "message_params": None,
            "progress": {"current": 0, "total": 0},
            "epoch": 0,
            "total_epochs": 0,
            "batch": 0,
            "batches": 0,
            "metrics": None,
            "validation": [],
            "previews": [],
            "exports": [],
            "bundle_url": None,
            "resumable": False,
            "device": None,
            "started_at": None,
            "finished_at": None,
            "epoch_seconds": None,
            "error": None,
        }

    def load_voice_state(self, voice: Voice | None) -> None:
        """Shows the last job of ``voice`` (no-op while a job is running)."""
        if self.is_running():
            return
        with self._lock:
            self.state = self._idle_state()
            self.state["voice_id"] = voice.id if voice else None
        self.log.clear()
        jobs = list_jobs(voice, running_job_id="") if voice else []
        if jobs:
            job = jobs[0]
            job_dir = voice.jobs_dir / job["job_id"]
            result = _read_json(job_dir / "result.json")
            total = int(job.get("max_epochs") or 0)
            epoch = int(result.get("epoch") or 0)
            with self._lock:
                self.state.update({
                    "status": job["status"],
                    "job_id": job["job_id"],
                    "name": job.get("name"),
                    "stage_key": job["status"],
                    "progress": {"current": epoch, "total": total},
                    "epoch": epoch,
                    "total_epochs": total,
                    "validation": result.get("validation") or [],
                    "previews": list_previews(job_dir, job["job_id"]),
                    "exports": job["exports"],
                    "bundle_url": job["bundle_url"],
                    "resumable": job["resumable"],
                    "error": result.get("error"),
                    "started_at": job.get("created_at"),
                    "finished_at": result.get("finished_at"),
                })
            log_file = job_dir / "train.log"
            if log_file.is_file():
                self.log.extend(log_file.read_text().splitlines()[-MAX_LOG_LINES:])
        self._publish("snapshot", self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = json.loads(json.dumps(self.state))
        snap["log_tail"] = list(self.log)[-80:]
        return snap

    def is_running(self) -> bool:
        return self.state["status"] in RUNNING

    # ----- pub/sub ---------------------------------------------------------
    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [(l, q) for l, q in self._subscribers if q is not queue]

    def _publish(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        with self._lock:
            subs = list(self._subscribers)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(self._put_nowait, queue, payload)
            except RuntimeError:
                pass

    @staticmethod
    def _put_nowait(queue: asyncio.Queue, payload: dict) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self.state.update(fields)
        self._publish("state", fields)

    def _log(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        self.log.append(line)
        self._publish("log", {"line": line})

    # ----- lifecycle -----------------------------------------------------------
    def start(self) -> dict[str, Any]:
        if self.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is already running"})
        voice = require_voice()
        settings = load_settings(voice)
        if not has_consent(voice):
            raise HTTPException(400, {"code": "consent_required", "message": "Record the voice owner's consent before training"})
        items = list_recordings(voice)
        minutes = total_minutes(items)
        if minutes < MIN_MINUTES:
            raise HTTPException(400, {"code": "too_little_audio", "message": f"At least {MIN_MINUTES:.0f} minutes of recordings are required (you have {minutes:.1f})"})
        language = settings["language"]
        job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        job_dir = voice.jobs_dir / job_id
        (job_dir / "dataset").mkdir(parents=True, exist_ok=True)
        # Piper's trainer reads "file|text"; "|" inside a transcript would break the CSV
        lines = [f"{r['id']}.wav|{r['text'].replace('|', ' ')}" for r in items]
        (job_dir / "dataset" / "metadata.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        training = dict(settings["training"])
        job = {
            "job_id": job_id,
            "voice_id": voice.id,
            "name": settings["name"],
            "slug": slugify(settings["name"]),
            "language": language,
            "piper_language": LANGUAGES[language]["piper"],
            "espeak_voice": LANGUAGES[language]["espeak"],
            "owner": settings["owner"],
            "consent": settings["consent"],
            "training": training,
            "max_epochs": int(training["epochs"]),
            "recordings": len(items),
            "minutes": round(minutes, 2),
            "audio_dir": str(voice.recordings_dir),
            "job_dir": str(job_dir),
            "base_checkpoint": str(base.base_path(language)),
            "test_sentences": LANGUAGES[language]["test_sentences"],
            "created_at": now(),
        }
        (job_dir / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False))
        prune_jobs(voice)
        self._launch(job, resume=False)
        return self.snapshot()

    def resume(self, extra_epochs: int = 0) -> dict[str, Any]:
        """Continues the current job from its last checkpoint, optionally with more epochs."""
        if self.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is already running"})
        job_id = self.state.get("job_id")
        if not job_id or not self.state.get("resumable"):
            raise HTTPException(409, {"code": "nothing_to_resume", "message": "No training run with a checkpoint to continue"})
        job_dir = find_job_dir(job_id)
        job = _read_json(job_dir / "job.json")
        if extra_epochs > 0:
            done = int(_read_json(job_dir / "result.json").get("epoch") or job["max_epochs"])
            job["max_epochs"] = max(int(job["max_epochs"]), done) + int(extra_epochs)
            (job_dir / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False))
        (job_dir / "result.json").unlink(missing_ok=True)
        self._launch(job, resume=True)
        return self.snapshot()

    def _launch(self, job: dict[str, Any], resume: bool) -> None:
        self.log.clear()
        self._cancel.clear()
        previous_validation = self.state.get("validation") if resume and self.state.get("job_id") == job["job_id"] else []
        with self._lock:
            self.state = self._idle_state()
        self._update(
            status="downloading",
            job_id=job["job_id"],
            voice_id=job.get("voice_id"),
            name=job.get("name"),
            stage_key="checking_base",
            total_epochs=int(job["max_epochs"]),
            validation=previous_validation or [],
            previews=list_previews(Path(job["job_dir"]), job["job_id"]),
            started_at=now(),
        )
        threading.Thread(target=self._run, args=(job, resume), daemon=True).start()

    def cancel(self) -> dict[str, Any]:
        if not self.is_running():
            raise HTTPException(409, {"code": "not_running", "message": "No training running"})
        self._cancel.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
        return self.snapshot()

    def _ensure_base(self, language: str) -> None:
        if base.is_installed(language):
            return
        meta = LANGUAGES[language]["base"]
        self._update(status="downloading", stage_key="downloading_base", message_params={"name": meta["name"]}, progress={"current": 0, "total": meta["size_mb"] << 20})
        self._log(f"Downloading base checkpoint {meta['name']}")

        def progress(info: dict) -> None:
            self._update(progress={"current": info["received"], "total": info.get("total") or (meta["size_mb"] << 20)})

        base.download(language, progress)

    def _fit_command(self, job: dict[str, Any], resume: bool) -> list[str]:
        job_dir = Path(job["job_dir"])
        t = job["training"]
        cmd = [
            sys.executable, "-m", "trainer.fit", "fit",
            "--data.voice_name", job["slug"],
            "--data.csv_path", str(job_dir / "dataset" / "metadata.csv"),
            "--data.audio_dir", job["audio_dir"],
            "--data.cache_dir", str(job_dir / "cache"),
            "--data.config_path", str(job_dir / "config.json"),
            "--data.espeak_voice", job["espeak_voice"],
            "--data.batch_size", str(int(t["batch_size"])),
            "--data.validation_split", "0.05",
            "--data.num_test_examples", "4",
            "--data.num_workers", "2",
            "--model.sample_rate", str(SAMPLE_RATE),
            "--model.learning_rate", str(float(t["learning_rate"])),
            "--model.learning_rate_d", str(float(t["learning_rate"]) / 2.0),
            "--trainer.max_epochs", str(int(job["max_epochs"])),
            "--trainer.check_val_every_n_epoch", str(int(t["validation_every"])),
            "--trainer.default_root_dir", str(job_dir),
            "--trainer.enable_progress_bar", "false",
            "--trainer.log_every_n_steps", "5",
        ]
        last = job_dir / "checkpoints" / "last.ckpt"
        if resume and last.exists():
            cmd += ["--ckpt_path", str(last)]
        else:
            cmd += ["--model.warmstart_ckpt", job["base_checkpoint"]]
        return cmd

    def _spawn(self, cmd: list[str], job: dict[str, Any]) -> int:
        job_dir = Path(job["job_dir"])
        env = dict(os.environ)
        env.update({
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(BACKEND_ROOT),
            "VT_CHECKPOINT_DIR": str(job_dir / "checkpoints"),
            "VT_PREVIEW_DIR": str(job_dir / "previews"),
            "VT_PREVIEW_EVERY": str(int(job["training"]["preview_every"])),
            "VT_ESPEAK_VOICE": job["espeak_voice"],
            "VT_TEST_SENTENCES": json.dumps(job.get("test_sentences") or [], ensure_ascii=False),
            "TORCH_HOME": str(Path(job["base_checkpoint"]).parent / "torch_hub"),
        })
        self._log(f"$ {' '.join(cmd)}")
        self._proc = subprocess.Popen(cmd, cwd=str(job_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        self._pump(self._proc)
        return self._proc.wait()

    def _run(self, job: dict[str, Any], resume: bool) -> None:
        job_dir = Path(job["job_dir"])
        try:
            self._ensure_base(job["language"])
            if self._cancel.is_set():
                raise InterruptedError
            self._update(status="preparing", stage_key="preparing", progress={"current": 0, "total": 0})
            code = self._spawn(self._fit_command(job, resume), job)
            if self._cancel.is_set():
                raise InterruptedError
            if code != 0:
                raise RuntimeError(f"Trainer exited with code {code}")
            self._export(job)
            self._update(status="done", stage_key="done", finished_at=now(), resumable=True, progress={"current": self.state["total_epochs"], "total": self.state["total_epochs"]})
            self._write_result(job_dir, "done")
        except InterruptedError:
            self._update(status="cancelled", stage_key="cancelled", finished_at=now(), resumable=(job_dir / "checkpoints" / "last.ckpt").exists())
            self._write_result(job_dir, "cancelled")
        except Exception as exc:  # noqa: BLE001
            self._log(f"ERROR: {exc}")
            self._update(status="failed", stage_key="failed", error=str(exc), finished_at=now(), resumable=(job_dir / "checkpoints" / "last.ckpt").exists())
            self._write_result(job_dir, "failed", error=str(exc))
        finally:
            self._proc = None
            if self.state.get("status") != "done":
                # voices exported by an earlier finished stretch of this run are still usable
                exports = list_exports(job_dir, job["job_id"])
                self._update(exports=exports, bundle_url=f"/api/jobs/{job['job_id']}/bundle" if exports else None)

    def _export(self, job: dict[str, Any], keep_checkpoints: bool = False) -> None:
        job_dir = Path(job["job_dir"])
        self._update(status="exporting", stage_key="exporting", progress={"current": 0, "total": 0})
        cmd = [sys.executable, "-m", "trainer.export", "--job", str(job_dir / "job.json")]
        if keep_checkpoints:
            cmd.append("--keep-checkpoints")
        code = self._spawn(cmd, job)
        if code != 0:
            raise RuntimeError("Export to ONNX failed")
        self._update(exports=list_exports(job_dir, job["job_id"]), bundle_url=f"/api/jobs/{job['job_id']}/bundle")

    def export_existing(self, job_id: str) -> dict[str, Any]:
        """Exports the checkpoints of a cancelled / interrupted job so its voice can still be used."""
        if self.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is already running"})
        job_dir = find_job_dir(job_id)
        job = _read_json(job_dir / "job.json")
        if not list((job_dir / "checkpoints").glob("*.ckpt")):
            raise HTTPException(409, {"code": "no_checkpoint", "message": "This run has no checkpoint yet"})
        self._cancel.clear()
        self._update(status="exporting", job_id=job_id, stage_key="exporting", error=None)

        def run() -> None:
            result = _read_json(job_dir / "result.json")
            previous = result.get("status") if result.get("status") in FINISHED else "cancelled"
            try:
                self._export(job, keep_checkpoints=True)
                if previous == "failed" and int(result.get("epoch") or 0) >= int(job.get("max_epochs") or 0) > 0:
                    # training itself had finished and only the export failed, so the run is complete now
                    previous = "done"
                    result.update(status="done", error=None)
                    (job_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
                self._update(status=previous, stage_key=previous, error=None)
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR: {exc}")
                self._update(status="failed", stage_key="failed", error=str(exc))
            finally:
                self._proc = None

        threading.Thread(target=run, daemon=True).start()
        return self.snapshot()

    def _pump(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        buf = b""
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while True:
                idx_n = buf.find(b"\n")
                idx_r = buf.find(b"\r")
                candidates = [i for i in (idx_n, idx_r) if i >= 0]
                if not candidates:
                    break
                idx = min(candidates)
                line = buf[:idx].decode("utf-8", errors="replace")
                buf = buf[idx + 1:]
                self._handle_line(line)
        if buf.strip():
            self._handle_line(buf.decode("utf-8", errors="replace"))

    def _handle_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        if not line.startswith("@@"):
            # progress bars of downloads (tqdm) redraw many times per second and would flood the log
            if not PROGRESS_BAR.match(line):
                self._log(line)
            return
        try:
            ev = json.loads(line[2:])
        except json.JSONDecodeError:
            self._log(line)
            return
        kind = ev.get("event")
        if kind == "train_start":
            self._epoch_started = time.time()
            self._update(status="training", stage_key="training", epoch=int(ev.get("epoch", 0)), total_epochs=int(ev.get("max_epochs", 0)), batches=int(ev.get("batches", 0)), device=ev.get("device"), progress={"current": int(ev.get("epoch", 0)), "total": int(ev.get("max_epochs", 0))})
            self._log(f"Training started on {ev.get('device')} at epoch {ev.get('epoch')} of {ev.get('max_epochs')}")
        elif kind == "step":
            self._update(batch=int(ev.get("batch", 0)), batches=int(ev.get("batches", 0)))
        elif kind == "epoch":
            started = getattr(self, "_epoch_started", None)
            seconds = round(time.time() - started, 2) if started else None
            self._epoch_started = time.time()
            epoch = int(ev.get("epoch", 0))
            self._update(epoch=epoch, batch=0, metrics={"loss_g": ev.get("loss_g"), "loss_d": ev.get("loss_d")}, epoch_seconds=seconds, progress={"current": epoch, "total": int(ev.get("max_epochs", self.state["total_epochs"]))})
        elif kind == "validation":
            entry = {"epoch": int(ev.get("epoch", 0)), "val_mel": ev.get("val_mel"), "val_mos": ev.get("val_mos"), "val_loss": ev.get("val_loss")}
            with self._lock:
                # a resumed run validates its starting epoch once more; keep one entry per epoch
                self.state["validation"] = [v for v in self.state["validation"] if v.get("epoch") != entry["epoch"]] + [entry]
                self.state["resumable"] = True
            self._publish("state", {"validation": self.state["validation"], "resumable": True})
            self._log(f"Epoch {entry['epoch']}: val_mel {entry['val_mel']}, val_mos {entry['val_mos']}")
        elif kind == "preview":
            job_id = self.state.get("job_id")
            if job_id:
                self._update(previews=list_previews(find_job_dir(job_id), job_id))
        elif kind == "progress":
            self._update(progress={"current": ev.get("current", 0), "total": ev.get("total", 0)})
        elif kind == "log":
            self._log(str(ev.get("message", "")))
        elif kind == "error":
            self._log(f"ERROR: {ev.get('message')}")

    def _write_result(self, job_dir: Path, status: str, error: str | None = None) -> None:
        result = {"status": status, "error": error, "finished_at": now(), "epoch": self.state.get("epoch"), "validation": self.state.get("validation")}
        (job_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        (job_dir / "train.log").write_text("\n".join(self.log))


manager = JobManager()


# ----- routes ---------------------------------------------------------------
@router.post("/train")
def start_training():
    return manager.start()


@router.post("/train/resume")
async def resume_training(request: Request):
    body: dict[str, Any] = {}
    try:
        if int(request.headers.get("content-length") or 0) > 0:
            body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return manager.resume(int((body or {}).get("extra_epochs") or 0))


@router.post("/train/cancel")
def cancel_training():
    return manager.cancel()


@router.get("/train")
def training_snapshot():
    return manager.snapshot()


@router.get("/train/status")
async def training_status_stream():
    loop = asyncio.get_running_loop()
    queue = manager.subscribe(loop)

    async def gen():
        try:
            yield _sse("snapshot", manager.snapshot())
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(item["event"], item["data"])
        finally:
            manager.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/jobs")
def get_jobs():
    voice = current_voice()
    return {"items": list_jobs(voice) if voice else []}


@router.post("/jobs/{job_id}/export")
def post_export(job_id: str):
    return manager.export_existing(job_id)


@router.get("/jobs/{job_id}/previews/{epoch}/{name}")
def get_preview(job_id: str, epoch: str, name: str):
    if not SAFE.match(epoch) or not SAFE.match(name):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad preview path"})
    path = find_job_dir(job_id) / "previews" / epoch / name
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Preview not found"})
    return FileResponse(path, media_type="audio/wav")


@router.get("/jobs/{job_id}/export/{name}")
def get_export(job_id: str, name: str):
    if not SAFE.match(name):
        raise HTTPException(400, {"code": "bad_id", "message": "Bad file name"})
    path = find_job_dir(job_id) / "export" / name
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "File not found"})
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.get("/jobs/{job_id}/log")
def job_log(job_id: str):
    log = find_job_dir(job_id) / "train.log"
    if not log.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Log not found"})
    return FileResponse(log, media_type="text/plain")


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job_dir = find_job_dir(job_id)
    if manager.is_running() and manager.state.get("job_id") == job_id:
        raise HTTPException(409, {"code": "already_running", "message": "Job is running"})
    shutil.rmtree(job_dir)
    if manager.state.get("job_id") == job_id:
        manager.load_voice_state(current_voice())
    return {"deleted": job_id}
