"""Paths, languages, voices (one voice = one project) and persisted settings.

Layout of the data volume:
    /data/base/<file>.ckpt                  downloaded Piper base checkpoints
    /data/prompts/<lang>.json               prepared sentence corpora
    /data/voices/<id>/voice.json            settings, owner, consent record
    /data/voices/<id>/consent.wav           spoken consent of the voice owner
    /data/voices/<id>/recordings/*.wav      22.05 kHz mono 16-bit recordings + recordings.json (texts)
    /data/voices/<id>/jobs/<job_id>/        training runs
    /data/current_voice                     id of the voice the UI works with
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
BASE_DIR = DATA_DIR / "base"
PROMPTS_DIR = DATA_DIR / "prompts"
VOICES_DIR = DATA_DIR / "voices"
CURRENT_FILE = DATA_DIR / "current_voice"
KEEP_JOBS = int(os.environ.get("KEEP_JOBS", "5"))
SAMPLE_RATE = 22050

HF_CHECKPOINTS = "https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/"
HF_VOICES = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
CV_SENTENCES = "https://raw.githubusercontent.com/common-voice/common-voice/main/server/data/"

LANGUAGES: dict[str, dict[str, Any]] = {
    "cs": {
        "label": "Čeština",
        "espeak": "cs",
        "piper": "cs_CZ",
        "base": {
            "name": "jirka (medium)",
            "file": "cs_CZ-jirka-medium.ckpt",
            "url": HF_CHECKPOINTS + "cs/cs_CZ/jirka/medium/epoch%3D8819-step%3D1435400.ckpt",
            "voice": "cs_CZ-jirka-medium",  # the released ONNX voice of the same checkpoint, for comparisons
            "voice_url": HF_VOICES + "cs/cs_CZ/jirka/medium/cs_CZ-jirka-medium.onnx",
            "epoch": 8819,
            "size_mb": 807,
            "license": "CC0 dataset",
        },
        "prompt_sources": [CV_SENTENCES + "cs/sentence-collector.txt"],
        "consent": "Já, {name}, souhlasím s tím, aby z mých nahrávek vznikl syntetický model mého hlasu.",
        "test_sentences": [
            "Dobrý den, tohle je zkouška mého nového hlasu.",
            "V obývacím pokoji je dvacet dva stupňů a světla jsou zhasnutá.",
            "Příliš žluťoučký kůň úpěl ďábelské ódy.",
            "Mám pustit rádio, nebo chcete raději ticho?",
            "Pračka doprala, nezapomeňte pověsit prádlo!",
        ],
    },
    "en": {
        "label": "English",
        "espeak": "en-us",
        "piper": "en_US",
        "base": {
            "name": "lessac (medium)",
            "file": "en_US-lessac-medium.ckpt",
            "url": HF_CHECKPOINTS + "en/en_US/lessac/medium/epoch%3D2164-step%3D1355540.ckpt",
            "voice": "en_US-lessac-medium",
            "voice_url": HF_VOICES + "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
            "epoch": 2164,
            "size_mb": 807,
            "license": "Blizzard 2013 (research use) dataset",
        },
        "prompt_sources": [CV_SENTENCES + "en/sentence-collector.txt"],
        "consent": "I, {name}, agree that a synthetic model of my voice is created from my recordings.",
        "test_sentences": [
            "Hello, this is a test of my new voice.",
            "The living room is twenty two degrees and the lights are off.",
            "The quick brown fox jumps over the lazy dog.",
            "Should I turn on the radio, or would you prefer silence?",
            "The washing machine has finished, do not forget the laundry!",
        ],
    },
}

DEFAULT_TRAINING = {
    "epochs": 500,  # fine-tuning epochs on top of the base checkpoint
    "batch_size": 16,
    "validation_every": 10,  # epochs between validation + checkpoint
    "preview_every": 50,  # epochs between audible previews (multiple of validation_every)
    "learning_rate": 0.0002,
    "patience": 5,  # validations without a better val_mel before the run stops by itself (0 = never)
    "quiet_pauses": True,  # fade the room noise down inside the pauses of the takes used for training
}

MIN_MINUTES = 5.0  # hard minimum to start training
RECOMMENDED_MINUTES = 30.0
TARGET_MINUTES = 60.0

_lock = threading.RLock()
VOICE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return text or "voice"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Voice:
    id: str

    @property
    def dir(self) -> Path:
        return VOICES_DIR / self.id

    @property
    def file(self) -> Path:
        return self.dir / "voice.json"

    @property
    def recordings_dir(self) -> Path:
        return self.dir / "recordings"

    @property
    def recordings_file(self) -> Path:
        return self.recordings_dir / "recordings.json"

    @property
    def consent_file(self) -> Path:
        return self.dir / "consent.wav"

    @property
    def jobs_dir(self) -> Path:
        return self.dir / "jobs"

    def ensure(self) -> "Voice":
        for d in (self.recordings_dir, self.jobs_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self


def _default_settings(name: str, language: str, owner: str) -> dict[str, Any]:
    return {
        "name": name,
        "language": language if language in LANGUAGES else "cs",
        "owner": owner,
        "consent": None,  # {"text": ..., "at": ..., "owner": ...} once recorded
        "max_record_seconds": 15.0,
        "training": dict(DEFAULT_TRAINING),
        "lexicon": {},  # word -> respelling that espeak pronounces right; applied when this app synthesises
        "skipped_prompts": [],
        "created_at": now(),
    }


def load_settings(voice: Voice) -> dict[str, Any]:
    with _lock:
        stored: dict[str, Any] = {}
        if voice.file.exists():
            try:
                stored = json.loads(voice.file.read_text())
            except json.JSONDecodeError:
                stored = {}
    settings = _default_settings(voice.id, stored.get("language", "cs"), stored.get("owner", ""))
    settings.update({k: v for k, v in stored.items() if k != "training"})
    settings["training"].update(stored.get("training", {}))
    return settings


def write_settings(voice: Voice, settings: dict[str, Any]) -> None:
    with _lock:
        voice.dir.mkdir(parents=True, exist_ok=True)
        voice.file.write_text(json.dumps(settings, indent=2, ensure_ascii=False))


def save_settings(voice: Voice, update: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings(voice)
    if "name" in update:
        settings["name"] = str(update["name"]).strip() or settings["name"]
    if "owner" in update:
        owner = str(update["owner"]).strip()
        if owner != settings["owner"]:
            settings["consent"] = None  # a consent is bound to the person who gave it
        settings["owner"] = owner
    if "lexicon" in update and isinstance(update["lexicon"], dict):
        lexicon = {}
        for word, spoken in list(update["lexicon"].items())[:500]:
            word, spoken = " ".join(str(word).split())[:60], " ".join(str(spoken).split())[:120]
            if word and spoken:
                lexicon[word] = spoken
        settings["lexicon"] = lexicon
    if "training" in update and isinstance(update["training"], dict):
        for key, default in DEFAULT_TRAINING.items():
            if key in update["training"] and update["training"][key] is not None:
                value = update["training"][key]
                settings["training"][key] = bool(value) if isinstance(default, bool) else type(default)(value)
        t = settings["training"]
        t["epochs"] = max(10, min(20000, t["epochs"]))
        t["batch_size"] = max(2, min(64, t["batch_size"]))
        t["validation_every"] = max(1, min(200, t["validation_every"]))
        t["patience"] = max(0, min(100, t["patience"]))
        t["preview_every"] = max(t["validation_every"], (t["preview_every"] // t["validation_every"]) * t["validation_every"])
    write_settings(voice, settings)
    return settings


# ----- voice registry -------------------------------------------------------------
def list_voices() -> list[dict[str, Any]]:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    current = current_voice_id()
    out = []
    for d in sorted(VOICES_DIR.iterdir()):
        if not d.is_dir() or not VOICE_ID.match(d.name):
            continue
        v = Voice(d.name)
        s = load_settings(v)
        out.append({
            "id": v.id,
            "name": s["name"],
            "language": s["language"],
            "owner": s["owner"],
            "has_consent": bool(s.get("consent")) and v.consent_file.exists(),
            "recordings": len(list(v.recordings_dir.glob("*.wav"))) if v.recordings_dir.exists() else 0,
            "jobs": len([j for j in v.jobs_dir.iterdir() if j.is_dir()]) if v.jobs_dir.exists() else 0,
            "created_at": s.get("created_at"),
            "current": v.id == current,
        })
    return out


def get_voice(vid: str) -> Voice:
    if not VOICE_ID.match(vid or "") or not (VOICES_DIR / vid).is_dir():
        raise KeyError(vid)
    return Voice(vid).ensure()


def create_voice(name: str, language: str, owner: str) -> Voice:
    base = slugify(name)[:32] or "voice"
    vid = base
    n = 2
    while (VOICES_DIR / vid).exists():
        vid = f"{base}-{n}"
        n += 1
    voice = Voice(vid).ensure()
    write_settings(voice, _default_settings(name.strip() or vid, language, owner.strip()))
    return voice


def delete_voice(vid: str) -> None:
    voice = get_voice(vid)
    shutil.rmtree(voice.dir)
    if current_voice_id() == vid:
        CURRENT_FILE.unlink(missing_ok=True)


def current_voice_id() -> str | None:
    try:
        vid = CURRENT_FILE.read_text().strip()
    except FileNotFoundError:
        return None
    return vid if VOICE_ID.match(vid) and (VOICES_DIR / vid).is_dir() else None


def select_voice(vid: str) -> Voice:
    voice = get_voice(vid)
    with _lock:
        CURRENT_FILE.write_text(voice.id)
    return voice


def current_voice() -> Voice | None:
    """The selected voice, the first existing one, or None when no voice was created yet."""
    vid = current_voice_id()
    if vid:
        return Voice(vid).ensure()
    voices = list_voices()
    if voices:
        return select_voice(voices[0]["id"])
    return None


for _d in (BASE_DIR, PROMPTS_DIR, VOICES_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def pronounce(text: str, lexicon: dict[str, str] | None, language: str) -> str:
    """The text as it is said, for turning into phonemes: the voice's own lexicon first, then the built-in list
    of loanwords and abbreviations espeak reads letter by letter. A word in the lexicon is never touched by the
    built-in list, so the lexicon can also switch a built-in respelling off (word -> the same word)."""
    from trainer.loanwords import respell

    lexicon = lexicon or {}
    return respell(apply_lexicon(text, lexicon), language, frozenset(w.lower() for w in lexicon) | frozenset(v.lower() for v in lexicon.values()))


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """Replaces whole words (case-insensitive) by their respelling, longest entries first."""
    if not lexicon:
        return text
    for word in sorted(lexicon, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lexicon[word], text, flags=re.IGNORECASE)
    return text
