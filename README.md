# Voice Trainer

A self-contained web app for recording a voice and fine-tuning a personal text-to-speech model from it:
a [Piper](https://github.com/OHF-Voice/piper1-gpl) voice you can use in Home Assistant, `wyoming-piper`
or on the command line.

Sister project of [wakeword-trainer](https://github.com/FilipChalupa/wakeword-trainer).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/hero-dark.png">
  <img alt="Voice Trainer recording studio" src="docs/screenshots/hero-light.png">
</picture>

## Consent first

A voice model can imitate a real person. Every voice here has a named owner, and training refuses to start until
the owner has read a consent statement aloud. The recording is stored next to the dataset, and nothing leaves
your machine: recordings, checkpoints and models live in the local `./data` folder.

Only train voices of people who agreed to it.

## How it works

1. **Voice** – name the voice, enter the owner's name, pick the language (Czech, English) and record the spoken consent.
2. **Recording studio** – sentences are shown one at a time. Press Space, read, and the recording stops by itself
   after you finish. The sentence is the transcript, so no speech recognition is involved. Each take gets quality
   checks (clipping, too quiet, cut off, length not matching the text); you can edit the transcript, re-record or
   add your own sentences. 5 minutes is the minimum, 30 minutes is recommended, 60 minutes is ideal.
3. **Training** – an existing Piper voice of the same language is fine-tuned on your recordings
   (`piper.train`, VITS, PyTorch Lightning). Progress is streamed live: epochs, losses, validation mel loss and an
   estimated MOS. Every N epochs the test sentences are synthesised so you can *hear* the progress. A run can be
   stopped, continued after a restart, or extended with more epochs.
4. **Test & export** – type text and listen, compare the last epoch with the best checkpoints, then download
   `<lang>-<name>-medium.onnx` + `.onnx.json` for Piper.

| Recording studio | Training |
| --- | --- |
| ![Recording studio](docs/screenshots/studio.png) | ![Training with live charts and previews](docs/screenshots/training.png) |
| **Voice and consent** | **Test & export** |
| ![Voice and consent](docs/screenshots/voice.png) | ![Test and export](docs/screenshots/test.png) |

Sentences come from the Common Voice sentence collection (CC0), filtered and ordered for phonetic variety. A short
built-in set works offline.

## Requirements

- Docker with Compose.
- An NVIDIA GPU with 8 GB+ of VRAM and `nvidia-container-toolkit` for training (works in WSL2). Recording and testing
  work without a GPU; training on a CPU is impractically slow.
- About 12 GB of disk for the image and the base checkpoint, plus ~1–4 GB per training run.

## Quick start

```bash
cp .env.example .env        # enables the GPU override and sets port 8001
docker compose up --build
```

Open <http://localhost:8001>. The microphone only works on `localhost` or over HTTPS.

Without a GPU: `docker compose -f docker-compose.yml up --build`.

Optional HTTP Basic auth: set `APP_PASSWORD` in `.env`.

## Using the voice

**Home Assistant (Piper add-on):** copy both files (`.onnx` and `.onnx.json`) into `/share/piper`, restart the
Piper add-on and reload the Wyoming integration. The voice then appears in the text-to-speech settings.

**wyoming-piper:**

```yaml
services:
  piper:
    image: rhasspy/wyoming-piper
    command: --voice cs_CZ-filip-medium
    volumes:
      - ./voices:/data        # put both files here
    ports:
      - "10200:10200"
```

**Command line:** `python3 -m piper -m cs_CZ-filip-medium.onnx -f out.wav -- "Dobrý den."`

## Training notes

- Fine-tuning starts from a published checkpoint (`cs_CZ-jirka-medium`, `en_US-lessac-medium`, ~800 MB, downloaded
  once) with a fresh optimizer; the learning rate decays to 5 % over the run.
- Default: 500 epochs, batch size 16. On an RTX 3080 with 30 minutes of audio an epoch takes a few seconds.
- A checkpoint is ~850 MB. Each run keeps the latest one (to continue from); the best-by-quality checkpoints are
  exported to ONNX and then removed. `KEEP_JOBS` (default 5) limits how many finished runs are kept per voice.
- The checkpoint to continue from is written at every validation, so stopping a run loses the epochs since the
  last one.
- The estimated MOS uses UTMOS, downloaded on first use. If it cannot be loaded, training still works and only the
  mel loss is shown.

## Project layout

```
backend/app        FastAPI: voices + consent, prompts, recordings, base checkpoints, jobs (manager + SSE),
                   synthesis/export, system info, static frontend
backend/trainer    fit.py (Piper trainer with progress/preview callbacks), export.py + onnx_export.py (ONNX export)
backend/tests      pytest suite (no PyTorch needed: pip install -r backend/requirements-dev.txt)
frontend           Vite + React + TypeScript + Material UI, Czech/English, light/dark by system setting
tests/e2e          Playwright smoke test used in CI, screenshots.js re-creates the README screenshots
data/              (runtime) base/, prompts/, voices/<id>/{recordings,jobs,consent.wav}
```

## API

| Method | Path | Description |
| --- | --- | --- |
| GET / POST / DELETE | `/api/voices` · `/api/voices/{id}/select` · `/api/voice` | Voices and settings |
| POST / GET / DELETE | `/api/consent` · `/api/consent/audio` | Spoken consent of the voice owner |
| GET / POST | `/api/prompts` · `/api/prompts/custom` · `/api/prompts/{id}/skip` | Sentences to read |
| GET / POST / PUT / DELETE | `/api/recordings` · `/api/recordings/{id}` · `…/audio` · `…/restore` | Recordings with transcripts |
| GET | `/api/dataset` | Dataset report and readiness |
| GET / POST | `/api/base` · `/api/base/{lang}/download` | Base checkpoints |
| POST / GET | `/api/train` · `/api/train/resume` · `/api/train/cancel` · `/api/train/status` (SSE) | Training |
| GET / POST / DELETE | `/api/jobs` · `/api/jobs/{id}/export` · `/api/jobs/{id}/bundle` · `…/previews/…` | Runs, previews, exported voices |
| POST | `/api/synthesize` | Text to speech with an exported voice |
| GET | `/api/system` | GPU, disk space, version |

## License

GPL-3.0-or-later. The trainer imports Piper's training code, which is GPL-3.0. Voices you train are yours;
check the licence of the base checkpoint you fine-tune from (the Czech `jirka` voice is based on a CC0 dataset,
the English `lessac` voice on a research-only dataset).
