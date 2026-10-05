"""Which sounds the recordings hold little of, and what to read to fill them in.

A voice says a sound well only if it heard it often enough; "dž", "dz", "ó", "au" or "eu" are rare in Czech text
and easily missing from half an hour of sentences. The texts go through the same path as for training
(lexicon, loanwords, numbers in words, espeak), so the count is of the sounds the model really gets.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from . import paragraphs, prompts
from .config import LANGUAGES, load_settings, phoneme_text, pronounce
from .recordings import load_index
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["coverage"])

LOW = 20  # fewer occurrences than this and the sound is likely to come out unsure

# label as written in Czech, the phoneme strings that count for it, the strings that contain it but are another sound
SOUNDS: dict[str, list[tuple[str, tuple[str, ...], tuple[str, ...]]]] = {
    "cs": [
        ("dž", ("dʒ",), ()), ("dz", ("dz", "dʑ"), ()), ("g", ("ɡ",), ()), ("f", ("f",), ()), ("ch", ("x",), ()),
        ("ř", ("r̝",), ()), ("ň", ("ɲ",), ()), ("ť", ("c",), ()), ("ď", ("ɟ",), ()), ("š", ("ʃ",), ("tʃ",)),
        ("ž", ("ʒ",), ("dʒ",)), ("č", ("tʃ",), ()), ("c", ("ts",), ()), ("ó", ("oː",), ()), ("é", ("eː",), ()),
        ("ú", ("uː",), ()), ("ou", ("oʊ",), ()), ("au", ("aʊ",), ()), ("eu", ("eʊ",), ()),
        ("slabičné r", ("r̩",), ()), ("slabičné l", ("l̩",), ()), ("n před k, g", ("ŋ",), ()),
    ],
}

_phonemizer = None
_cache: dict[tuple[str, str], str] = {}


def phonemes(text: str, espeak_voice: str) -> str:
    """espeak's phonemes of a text, stress marks left out. Raises ImportError where Piper is not installed."""
    global _phonemizer
    key = (espeak_voice, text)
    if key not in _cache:
        if _phonemizer is None:
            from piper.phonemize_espeak import EspeakPhonemizer

            _phonemizer = EspeakPhonemizer()
        if len(_cache) > 50000:
            _cache.clear()
        _cache[key] = " ".join("".join(s) for s in _phonemizer.phonemize(espeak_voice, text)).replace("ˈ", "").replace("ˌ", "")
    return _cache[key]


def count_sounds(texts: list[str], language: str, lexicon: dict[str, str]) -> dict[str, int]:
    espeak_voice = LANGUAGES[language]["espeak"]
    counts = {label: 0 for label, _, _ in SOUNDS.get(language, [])}
    for text in texts:
        ph = phonemes(phoneme_text(text, lexicon, language), espeak_voice)
        for label, strings, inside in SOUNDS.get(language, []):
            counts[label] += sum(ph.count(s) for s in strings) - sum(ph.count(s) for s in inside)
    return counts


@router.get("/dataset/coverage")
def get_coverage() -> dict[str, Any]:
    voice = require_voice()
    settings = load_settings(voice)
    language, lexicon = settings["language"], settings.get("lexicon") or {}
    if language not in SOUNDS:
        return {"available": False, "items": [], "suggest": [], "low": LOW}
    index = load_index(voice)
    try:
        counts = count_sounds([e.get("text", "") for e in index.values()], language, lexicon)
    except ImportError:
        return {"available": False, "items": [], "suggest": [], "low": LOW}
    items = sorted(({"sound": label, "count": n, "low": n < LOW} for label, n in counts.items()), key=lambda i: i["count"])
    low = [i["sound"] for i in items if i["low"]]
    suggest = []
    if low:
        recorded = {e.get("prompt_id") for e in index.values()}
        for p in paragraphs.BUILTIN.get(language, []):
            left = [s for s in prompts.split_sentences(p["text"]) if prompts.prompt_id(s) not in recorded]
            gain = count_sounds(left, language, lexicon) if left else {}
            total = sum(gain.get(s, 0) for s in low)
            if total:
                suggest.append({"id": p["id"], "title": p["title"], "gain": total, "sounds": [s for s in low if gain.get(s)]})
        suggest.sort(key=lambda s: -s["gain"])
    return {"available": True, "items": items, "suggest": suggest[:4], "low": LOW}


@router.post("/pronounce")
def post_pronounce(body: dict[str, Any]) -> dict[str, Any]:
    """The text written the way it is said: paste the result where no lexicon exists (Piper in Home Assistant)."""
    voice = require_voice()
    settings = load_settings(voice)
    text = str(body.get("text", ""))[:5000]
    return {"text": pronounce(text, settings.get("lexicon") or {}, settings["language"])}
