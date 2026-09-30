"""Exports checkpoints of a job to Piper voices (ONNX + JSON config) and removes the bulky leftovers."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def emit(event: str, **data) -> None:
    print("@@" + json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def export_checkpoint(checkpoint: Path, output: Path, config: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "trainer.onnx_export", "--checkpoint", str(checkpoint), "--output-file", str(output)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not output.exists():
        raise RuntimeError(f"ONNX export failed for {checkpoint.name}: {(proc.stderr or proc.stdout)[-600:]}")
    shutil.copyfile(config, Path(str(output) + ".json"))


def variant_of(checkpoint: Path) -> str:
    name = checkpoint.stem
    if name.startswith("last"):
        return "last"
    if name.startswith("best_mos"):
        return "best_mos"
    if name.startswith("best_mel"):
        return "best_mel"
    return name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--keep-checkpoints", action="store_true", help="Do not delete non-last checkpoints after export")
    args = parser.parse_args()
    job = json.loads(Path(args.job).read_text())
    job_dir = Path(job["job_dir"])
    ckpt_dir = job_dir / "checkpoints"
    config = job_dir / "config.json"
    export_dir = job_dir / "export"
    checkpoints = sorted(ckpt_dir.glob("*.ckpt"))
    if not checkpoints:
        raise RuntimeError("No checkpoint to export – training did not reach its first validation")
    if not config.exists():
        raise RuntimeError("Voice config.json is missing")
    base_name = f"{job['piper_language']}-{job['slug']}-medium"
    exported = []
    for i, ckpt in enumerate(checkpoints, start=1):
        variant = variant_of(ckpt)
        # the latest checkpoint carries the plain Piper voice name; alternates get a suffix
        name = base_name if variant == "last" else f"{base_name}.{variant}"
        target = export_dir / f"{name}.onnx"
        emit("progress", current=i - 1, total=len(checkpoints))
        export_checkpoint(ckpt, target, config)
        exported.append({"variant": variant, "file": target.name, "checkpoint": ckpt.name, "size": target.stat().st_size})
        emit("log", message=f"Exported {ckpt.name} -> {target.name} ({target.stat().st_size // (1 << 20)} MB)")
    (export_dir / "exports.json").write_text(json.dumps(exported, indent=2))
    # voices of checkpoints that no longer exist (an earlier export of a resumed run) would only confuse
    keep = {e["file"] for e in exported}
    for stale in export_dir.glob("*.onnx"):
        if stale.name not in keep:
            stale.unlink(missing_ok=True)
            Path(str(stale) + ".json").unlink(missing_ok=True)
    if not args.keep_checkpoints:
        for ckpt in checkpoints:
            if not ckpt.stem.startswith("last"):
                ckpt.unlink(missing_ok=True)
    # onnxruntime's telemetry drops a ":memory:.ses" file into the working directory
    for junk in job_dir.glob(":memory:*"):
        junk.unlink(missing_ok=True)
    emit("exported", files=exported)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        emit("error", message=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
