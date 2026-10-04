"""Live training: fine-tunes a Piper voice in a subprocess, parses its progress, streams it via SSE.
Stored runs (summaries, exports, previews) live in runs.py."""
from __future__ import annotations

import asyncio
import json
import os
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
from starlette.concurrency import run_in_threadpool

from . import base
from .audio import processing_active
from .config import LANGUAGES, MIN_MINUTES, SAMPLE_RATE, Voice, current_voice, list_voices, load_settings, now, pronounce, slugify
from .events import PROGRESS_BAR, parse_event, pump
from .recordings import list_recordings, total_minutes
from .runs import FINISHED, SAFE, calibration, find_job_dir, list_exports, list_jobs, list_previews, prune_jobs, read_json
from .voices import has_consent, require_voice

router = APIRouter(prefix="/api", tags=["training"])

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MAX_LOG_LINES = 600
RUNNING = ("downloading", "preparing", "training", "exporting")
STOP_FILE = "STOP"  # created in the job directory to ask the trainer for a clean stop
WARMSTART_FILE = "warmstart.ckpt"  # an earlier run's checkpoint this run starts from (a hard link, removed afterwards)


def prepare_training_audio(voice: Voice, items: list[dict[str, Any]], target: Path, quiet: bool = True, processing: dict[str, float] | None = None) -> None:
    """Copies of the takes for training: tone correction first, then the pauses faded down. The takes stay."""
    import soundfile as sf

    from .audio import apply_processing, quiet_pauses

    target.mkdir(parents=True, exist_ok=True)
    for r in items:
        data, sr = sf.read(str(voice.recordings_dir / f"{r['id']}.wav"), dtype="float32", always_2d=True)
        audio = apply_processing(data[:, 0], sr, processing)
        sf.write(str(target / f"{r['id']}.wav"), quiet_pauses(audio, sr) if quiet else audio, sr, subtype="PCM_16")


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
            "stopped_early": False,
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
            result = read_json(job_dir / "result.json")
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
    def start(self, from_job: str | None = None) -> dict[str, Any]:
        """Starts a new run on the current recordings. It begins from the published base voice, or with
        ``from_job`` from the last checkpoint of an earlier run of this voice (continuing with more data)."""
        if self.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is already running"})
        self._require_gpu_free()
        voice = require_voice()
        source: Path | None = None
        if from_job:
            source = find_job_dir(from_job) / "checkpoints" / "last.ckpt"
            if source.parent.parent.parent != voice.jobs_dir or not source.exists():
                raise HTTPException(409, {"code": "no_checkpoint", "message": "That run has no checkpoint to start from"})
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
        lexicon = settings.get("lexicon") or {}
        lines = training_lines(items, lexicon, language)
        (job_dir / "dataset" / "metadata.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        training = dict(settings["training"])
        audio_dir = voice.recordings_dir
        processing = settings.get("processing") or {}
        if training.get("quiet_pauses", True) or processing_active(processing):
            # the takes go in tone-corrected and with their pauses faded down; the originals stay as they are
            audio_dir = job_dir / "dataset" / "audio"
            prepare_training_audio(voice, items, audio_dir, bool(training.get("quiet_pauses", True)), processing)
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
            "processing": processing if processing_active(processing) else None,
            "max_epochs": int(training["epochs"]),
            "recordings": len(items),
            "minutes": round(minutes, 2),
            "audio_dir": str(audio_dir),
            "job_dir": str(job_dir),
            "base_checkpoint": str(base.base_path(language)),
            "from_job": from_job or None,
            "test_sentences": [pronounce(t, lexicon, language) for t in LANGUAGES[language]["test_sentences"]],
            "created_at": now(),
        }
        (job_dir / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False))
        if source is not None:
            # a hard link: no copy of 850 MB, and it survives the source run being pruned or deleted
            try:
                os.link(source, job_dir / WARMSTART_FILE)
            except OSError:
                shutil.copyfile(source, job_dir / WARMSTART_FILE)
        prune_jobs(voice)
        self._launch(job, resume=False)
        return self.snapshot()

    def resume(self, extra_epochs: int = 0) -> dict[str, Any]:
        """Continues the current job from its last checkpoint, optionally with more epochs."""
        if self.is_running():
            raise HTTPException(409, {"code": "already_running", "message": "Training is already running"})
        self._require_gpu_free()
        job_id = self.state.get("job_id")
        if not job_id or not self.state.get("resumable"):
            raise HTTPException(409, {"code": "nothing_to_resume", "message": "No training run with a checkpoint to continue"})
        job_dir = find_job_dir(job_id)
        job = read_json(job_dir / "job.json")
        if extra_epochs > 0:
            done = int(read_json(job_dir / "result.json").get("epoch") or job["max_epochs"])
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

    @staticmethod
    def _require_gpu_free() -> None:
        from .importer import transcriber
        from .verify import verifier

        if transcriber.is_running():
            raise HTTPException(409, {"code": "import_running", "message": "A recording is being transcribed; start training afterwards"})
        verifier.stop()  # the flow-mode checker keeps Whisper on the GPU only between requests; training has priority

    def cancel(self) -> dict[str, Any]:
        if not self.is_running():
            raise HTTPException(409, {"code": "not_running", "message": "No training running"})
        self._cancel.set()
        proc = self._proc
        if proc and proc.poll() is None:
            if self.state.get("status") == "training" and self.state.get("job_id"):
                # ask the trainer to save its state first; it exits by itself, the kill is only a safety net
                (find_job_dir(self.state["job_id"]) / STOP_FILE).touch()
                self._update(stage_key="stopping")
                threading.Thread(target=self._terminate_later, args=(proc, 180), daemon=True).start()
            else:
                proc.terminate()
        return self.snapshot()

    @staticmethod
    def _terminate_later(proc: subprocess.Popen, seconds: float) -> None:
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()

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
            own = job_dir / WARMSTART_FILE
            cmd += ["--model.warmstart_ckpt", str(own) if own.exists() else job["base_checkpoint"]]
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
            "VT_STOP_FILE": str(job_dir / STOP_FILE),
            "VT_PATIENCE": str(int(job["training"].get("patience", 0))),
            "TORCH_HOME": str(Path(job["base_checkpoint"]).parent / "torch_hub"),
        })
        (job_dir / STOP_FILE).unlink(missing_ok=True)
        self._log(f"$ {' '.join(cmd)}")
        self._proc = subprocess.Popen(cmd, cwd=str(job_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        pump(self._proc, self._handle_line)
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
            if (job_dir / "checkpoints" / "last.ckpt").exists():
                (job_dir / WARMSTART_FILE).unlink(missing_ok=True)  # only needed until the run has its own checkpoint
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
        job = read_json(job_dir / "job.json")
        if not list((job_dir / "checkpoints").glob("*.ckpt")):
            raise HTTPException(409, {"code": "no_checkpoint", "message": "This run has no checkpoint yet"})
        self._cancel.clear()
        self._update(status="exporting", job_id=job_id, stage_key="exporting", error=None)

        def run() -> None:
            result = read_json(job_dir / "result.json")
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

    def _handle_line(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        ev = parse_event(line)
        if ev is None:
            # progress bars of downloads (tqdm) redraw many times per second and would flood the log
            if not PROGRESS_BAR.match(line):
                self._log(line)
            return
        kind = ev.get("event")
        if kind == "train_start":
            self._epoch_started = time.time()
            self._epoch_times = []
            self._update(status="training", stage_key="training", epoch=int(ev.get("epoch", 0)), total_epochs=int(ev.get("max_epochs", 0)), batches=int(ev.get("batches", 0)), device=ev.get("device"), progress={"current": int(ev.get("epoch", 0)), "total": int(ev.get("max_epochs", 0))})
            self._log(f"Training started on {ev.get('device')} at epoch {ev.get('epoch')} of {ev.get('max_epochs')}")
        elif kind == "step":
            self._update(batch=int(ev.get("batch", 0)), batches=int(ev.get("batches", 0)))
        elif kind == "epoch":
            started = getattr(self, "_epoch_started", None)
            seconds = round(time.time() - started, 2) if started else None
            self._epoch_started = time.time()
            if seconds:
                self._epoch_times.append(seconds)
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
        elif kind == "early_stop":
            self._update(stopped_early=True)
            self._log(f"Stopped early at epoch {ev.get('epoch')}: val_mel did not improve for {ev.get('patience')} validations")
        elif kind == "stopped":
            self._log(f"Stopped at epoch {int(ev.get('epoch', 0)) + 1}, batch {ev.get('batch')}; checkpoint saved")
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
        times = sorted(getattr(self, "_epoch_times", []))
        result = {
            "status": status,
            "error": error,
            "finished_at": now(),
            "epoch": self.state.get("epoch"),
            "validation": self.state.get("validation"),
            # typical epoch length of this run, used to estimate the next one
            "epoch_seconds": times[len(times) // 2] if times else None,
            "stopped_early": bool(self.state.get("stopped_early")),
            "device": self.state.get("device"),
        }
        (job_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        (job_dir / "train.log").write_text("\n".join(self.log))


manager = JobManager()


def training_lines(items: list[dict[str, Any]], lexicon: dict[str, str], language: str) -> list[str]:
    """Piper's trainer reads "file|text"; "|" inside a transcript would break the CSV. Words that are not said
    as written (the voice's lexicon, loanwords) are respelled, so the phonemes match what was actually spoken."""
    return [f"{r['id']}.wav|{pronounce(r['text'], lexicon, language).replace('|', ' ')}" for r in items]


# ----- routes ---------------------------------------------------------------
@router.post("/train")
async def start_training(request: Request):
    body: dict[str, Any] = {}
    try:
        if int(request.headers.get("content-length") or 0) > 0:
            body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await run_in_threadpool(manager.start, str((body or {}).get("from_job") or "") or None)



@router.get("/train/calibration")
def get_calibration():
    return calibration()


def suggest_training(minutes: float) -> dict[str, Any]:
    """Starting points by the amount of audio: a small set needs more passes and more patience (its validation
    is noisy), a large one converges in fewer epochs. Rules of thumb from fine-tuning runs, not a law."""
    if minutes < 10:
        return {"epochs": 800, "validation_every": 10, "preview_every": 50, "patience": 12}
    if minutes < 30:
        return {"epochs": 600, "validation_every": 10, "preview_every": 50, "patience": 10}
    if minutes < 60:
        return {"epochs": 500, "validation_every": 10, "preview_every": 50, "patience": 8}
    return {"epochs": 400, "validation_every": 10, "preview_every": 50, "patience": 6}


@router.get("/train/suggest")
def get_suggest():
    voice = require_voice()
    minutes = total_minutes(list_recordings(voice))
    return {"minutes": round(minutes, 1), "training": suggest_training(minutes)}


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
def get_jobs(all: bool = False):
    """Runs of the current voice, or with ``all`` the finished runs of every voice (to compare voices)."""
    if all:
        items = []
        for entry in list_voices():
            for job in list_jobs(Voice(entry["id"])):
                items.append({**job, "voice_name": entry["name"]})
        return {"items": items}
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
