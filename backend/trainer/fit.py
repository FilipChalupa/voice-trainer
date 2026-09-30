"""Fine-tuning entry point: Piper's VITS trainer with our own callbacks.

Same CLI as ``python -m piper.train`` (LightningCLI), but:
  * progress is reported on stdout as ``@@{json}`` lines the API parses,
  * at most a handful of checkpoints are kept (each is ~850 MB),
  * every N epochs a fixed set of sentences is synthesised to WAV so progress can be heard.

Configuration comes from environment variables set by the job manager:
  VT_CHECKPOINT_DIR, VT_PREVIEW_DIR, VT_PREVIEW_EVERY, VT_ESPEAK_VOICE, VT_TEST_SENTENCES (JSON list)
"""
from __future__ import annotations

import itertools
import json
import logging
import os
import time
from pathlib import Path

import torch
from lightning.pytorch.callbacks import Callback, ModelCheckpoint
from lightning.pytorch.cli import LightningCLI
from piper.train.vits.dataset import VitsDataModule
from piper.train.vits.lightning import VitsModel


def emit(event: str, **data) -> None:
    print("@@" + json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def _scalar(value) -> float | None:
    try:
        return float(value.detach().cpu().item() if hasattr(value, "detach") else value)
    except Exception:  # noqa: BLE001
        return None


class ProgressCallback(Callback):
    """Reports epochs, losses, validation metrics and writes audible previews."""

    def __init__(self) -> None:
        self._last_step_emit = 0.0
        self.preview_dir = Path(os.environ.get("VT_PREVIEW_DIR", "previews"))
        self.preview_every = max(1, int(os.environ.get("VT_PREVIEW_EVERY", "50")))
        self.espeak_voice = os.environ.get("VT_ESPEAK_VOICE", "cs")
        try:
            self.sentences = list(json.loads(os.environ.get("VT_TEST_SENTENCES", "[]")))
        except json.JSONDecodeError:
            self.sentences = []
        self._phonemizer = None

    # ----- progress -----
    def on_train_start(self, trainer, pl_module) -> None:
        emit("train_start", epoch=int(trainer.current_epoch), max_epochs=int(trainer.max_epochs), batches=int(trainer.num_training_batches), device=str(pl_module.device))

    def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx) -> None:
        now = time.time()
        if now - self._last_step_emit < 0.5:
            return
        self._last_step_emit = now
        emit("step", epoch=int(trainer.current_epoch), batch=int(batch_idx) + 1, batches=int(trainer.num_training_batches))

    def on_train_epoch_end(self, trainer, pl_module) -> None:
        m = trainer.callback_metrics
        emit("epoch", epoch=int(trainer.current_epoch) + 1, max_epochs=int(trainer.max_epochs), loss_g=_scalar(m.get("loss_g")), loss_d=_scalar(m.get("loss_d")))

    def on_validation_end(self, trainer, pl_module) -> None:
        # not on_validation_epoch_end: the model logs val_mos in its own epoch-end hook, which runs after the callbacks' one
        if trainer.sanity_checking:
            return
        m = trainer.callback_metrics
        epoch = int(trainer.current_epoch) + 1
        emit("validation", epoch=epoch, val_mel=_scalar(m.get("val_mel")), val_mos=_scalar(m.get("val_mos")), val_loss=_scalar(m.get("val_loss")))
        if self.sentences and (epoch % self.preview_every == 0 or epoch == int(trainer.max_epochs)):
            try:
                self._write_previews(pl_module, epoch)
            except Exception as exc:  # noqa: BLE001  (a failed preview must never stop training)
                emit("log", message=f"Preview failed at epoch {epoch}: {exc}")

    # ----- previews -----
    def _phoneme_ids(self, text: str) -> list[int]:
        from piper.phoneme_ids import phonemes_to_ids
        from piper.phonemize_espeak import EspeakPhonemizer

        if self._phonemizer is None:
            self._phonemizer = EspeakPhonemizer()
        sentences = self._phonemizer.phonemize(self.espeak_voice, text)
        return list(itertools.chain(*(phonemes_to_ids(s) for s in sentences)))

    def _write_previews(self, pl_module, epoch: int) -> None:
        import soundfile as sf

        out_dir = self.preview_dir / f"epoch_{epoch:05d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        was_training = pl_module.training
        pl_module.eval()
        try:
            for idx, text in enumerate(self.sentences):
                ids = self._phoneme_ids(text)
                if not ids:
                    continue
                tokens = torch.LongTensor(ids).unsqueeze(0).to(pl_module.device)
                lengths = torch.LongTensor([len(ids)]).to(pl_module.device)
                with torch.inference_mode():
                    audio = pl_module(tokens, lengths, [0.667, 1.0, 0.8]).detach().float().cpu().numpy().reshape(-1)
                peak = max(0.01, float(abs(audio).max()))
                path = out_dir / f"{idx}.wav"
                sf.write(str(path), audio * (0.9 / peak), int(pl_module.hparams.sample_rate), subtype="PCM_16")
                files.append(path.name)
        finally:
            if was_training:
                pl_module.train()
        (out_dir / "sentences.json").write_text(json.dumps(self.sentences, ensure_ascii=False))
        emit("preview", epoch=epoch, files=files)


class OptionalMetricCheckpoint(ModelCheckpoint):
    """ModelCheckpoint that stays idle while its monitored metric is not being logged.

    "val_mos" only exists when the UTMOS predictor could be loaded (it needs a download on first use);
    a plain ModelCheckpoint raises when the key is missing, which would abort the whole run.
    """

    def on_validation_end(self, trainer, pl_module) -> None:
        if self.monitor and self.monitor not in trainer.callback_metrics:
            return
        super().on_validation_end(trainer, pl_module)


class VitsLightningCLI(LightningCLI):
    def add_arguments_to_parser(self, parser):
        parser.link_arguments("data.batch_size", "model.batch_size")
        parser.link_arguments("data.num_symbols", "model.num_symbols")
        parser.link_arguments("model.num_speakers", "data.num_speakers")
        parser.link_arguments("model.sample_rate", "data.sample_rate")
        parser.link_arguments("model.filter_length", "data.filter_length")
        parser.link_arguments("model.hop_length", "data.hop_length")
        parser.link_arguments("model.win_length", "data.win_length")
        parser.link_arguments("model.segment_size", "data.segment_size")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.deterministic = False
    ckpt_dir = os.environ.get("VT_CHECKPOINT_DIR", "checkpoints")
    callbacks = [
        # best reconstruction + always the latest (needed to resume / continue)
        ModelCheckpoint(dirpath=ckpt_dir, monitor="val_mel", mode="min", save_top_k=1, save_last=True, filename="best_mel-epoch={epoch}", auto_insert_metric_name=False),
        # best perceived quality (UTMOS); silently inactive when the predictor cannot be loaded
        OptionalMetricCheckpoint(dirpath=ckpt_dir, monitor="val_mos", mode="max", save_top_k=1, save_last=False, filename="best_mos-epoch={epoch}", auto_insert_metric_name=False),
        ProgressCallback(),
    ]
    VitsLightningCLI(VitsModel, VitsDataModule, trainer_defaults={"max_epochs": -1, "callbacks": callbacks})


if __name__ == "__main__":
    main()
