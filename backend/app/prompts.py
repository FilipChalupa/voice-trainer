"""Sentences to read: a prepared corpus per language (Common Voice, CC0) + custom prompts per voice."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
from typing import Any

import requests

from .config import LANGUAGES, PROMPTS_DIR, Voice, load_settings, write_settings

CORPUS_SIZE = 1500
_prepare_lock = threading.Lock()
_preparing: dict[str, dict[str, Any]] = {}

# Small offline fallbacks; the full corpus is downloaded and prepared on first use.
BUILTIN: dict[str, list[str]] = {
    "cs": [
        "Dobrý den, jak se dnes máte?",
        "Příliš žluťoučký kůň úpěl ďábelské ódy.",
        "V neděli ráno jsme šli na procházku kolem řeky.",
        "Můžeš mi prosím podat tu modrou knihu z police?",
        "Zítra má být slunečno a teploty vystoupí k pětadvaceti stupňům.",
        "Babička upekla švestkový koláč a celý dům krásně voněl.",
        "Nechoď tam, je to nebezpečné!",
        "Kolik stojí jízdenka do Brna a zpátky?",
        "Děti si hrály na zahradě, dokud se nesetmělo.",
        "Tchyně přijede ve čtvrtek odpoledne vlakem z Olomouce.",
        "Šest set šedesát šest stříbrných křepelek přeletělo přes střechu.",
        "Počítač se zase zasekl, musím ho restartovat.",
        "Řekni mi, co si o tom opravdu myslíš.",
        "Na stole ležel hrnek s čajem a rozečtené noviny.",
        "Dědeček vyprávěl příběhy ze svého mládí.",
        "Ještě jednou ti děkuji za pomoc, moc si toho vážím.",
        "Vlak do Prahy má dvacet minut zpoždění.",
        "Ťukal na dveře, ale nikdo neotevřel.",
        "Proč jsi mi to neřekl dřív?",
        "V lese rostou houby, maliny a ostružiny.",
        "Chtěl bych si objednat jednu kávu s mlékem a kousek dortu.",
        "Sousedův pes štěkal celou noc a nikdo nemohl spát.",
        "Hned jak dopíšu tenhle dopis, půjdu nakoupit.",
        "Žádný učený z nebe nespadl.",
        "Rozsviť světlo v kuchyni a zhasni v předsíni.",
        "Na jaře kvetou třešně a louky se zelenají.",
        "Džbán s vodou stál na okně vedle květináče.",
        "Myslím, že bychom měli vyrazit o něco dřív.",
        "Eva a Aleš jeli autobusem na výlet do hor.",
        "Tohle je poslední věta z krátké zkušební sady.",
    ],
    "en": [
        "Good morning, how are you today?",
        "The quick brown fox jumps over the lazy dog.",
        "We went for a walk along the river on Sunday morning.",
        "Could you please hand me the blue book from the shelf?",
        "Tomorrow should be sunny with temperatures around seventy degrees.",
        "Grandma baked a plum cake and the whole house smelled wonderful.",
        "Do not go there, it is dangerous!",
        "How much is a return ticket to Boston?",
        "The children played in the garden until it got dark.",
        "She sells seashells by the seashore.",
        "The computer froze again, so I have to restart it.",
        "Tell me what you really think about it.",
        "A cup of tea and an open newspaper lay on the table.",
        "Grandfather told stories from his youth.",
        "Thank you once again for your help, I really appreciate it.",
        "The train to London is twenty minutes late.",
        "He knocked on the door, but nobody answered.",
        "Why did you not tell me earlier?",
        "Mushrooms, raspberries and blackberries grow in the forest.",
        "I would like to order a coffee with milk and a slice of cake.",
        "The neighbour's dog barked all night and nobody could sleep.",
        "As soon as I finish this letter, I will go shopping.",
        "Practice makes perfect.",
        "Turn on the light in the kitchen and turn it off in the hall.",
        "Cherry trees bloom in spring and the meadows turn green.",
        "A jug of water stood on the window next to a flower pot.",
        "I think we should leave a little earlier.",
        "Eve and Alex took the bus for a trip to the mountains.",
        "Measure twice and cut once, as the old carpenters say.",
        "This is the last sentence of the short test set.",
    ],
}

_ALLOWED = {
    "cs": re.compile(r"^[A-Za-zÁČĎÉĚÍŇÓŘŠŤÚŮÝŽáčďéěíňóřšťúůýž ,.?!;:'\"„“–-]+$"),
    "en": re.compile(r"^[A-Za-z ,.?!;:'\"“”–-]+$"),
}


def prompt_id(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().strip('"').strip())


def filter_sentences(lines: list[str], language: str) -> list[str]:
    """Keeps natural, readable sentences: 6-16 words, 35-120 characters, only the language's alphabet."""
    allowed = _ALLOWED.get(language, _ALLOWED["en"])
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        s = _clean(raw)
        if not (35 <= len(s) <= 120) or not allowed.match(s):
            continue
        words = s.split()
        if not (6 <= len(words) <= 16) or s.isupper() or not s[0].isupper():
            continue
        if s[-1] not in ".?!":
            s += "."
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def select_balanced(sentences: list[str], size: int, seed: int = 7) -> list[str]:
    """Greedy ordering by phonetic variety: each pick adds the most new letter pairs (a cheap diphone proxy),
    so even the first 100 sentences already cover the language's sound combinations well."""
    rng = random.Random(seed)
    pool = list(sentences)
    rng.shuffle(pool)
    covered: set[str] = set()
    chosen: list[str] = []

    def pairs(s: str) -> set[str]:
        t = re.sub(r"[^a-záčďéěíňóřšťúůýž ]", "", s.lower())
        return {t[i : i + 2] for i in range(len(t) - 1)}

    pair_cache = {s: pairs(s) for s in pool}
    while pool and len(chosen) < size:
        sample = pool if len(pool) <= 300 else rng.sample(pool, 300)
        best = max(sample, key=lambda s: (len(pair_cache[s] - covered) / (len(s) ** 0.5), rng.random()))
        chosen.append(best)
        covered |= pair_cache[best]
        pool.remove(best)
    return chosen


def corpus_path(language: str):
    return PROMPTS_DIR / f"{language}.json"


def prepare_corpus(language: str) -> list[dict[str, str]]:
    """Downloads the language's sentence sources, filters and orders them. Blocking."""
    meta = LANGUAGES[language]
    lines: list[str] = []
    for url in meta["prompt_sources"]:
        with requests.get(url, timeout=60, stream=True) as resp:
            resp.raise_for_status()
            size = 0
            for line in resp.iter_lines(decode_unicode=True):
                if line:
                    lines.append(line)
                    size += len(line)
                if size > 30_000_000:
                    break
    sentences = select_balanced(filter_sentences(lines, language), CORPUS_SIZE)
    if len(sentences) < 100:
        raise RuntimeError(f"Only {len(sentences)} usable sentences found")
    corpus = [{"id": prompt_id(s), "text": s} for s in sentences]
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    corpus_path(language).write_text(json.dumps(corpus, ensure_ascii=False))
    return corpus


def _prepare_in_background(language: str) -> None:
    with _prepare_lock:
        state = _preparing.get(language)
        if state and state.get("state") == "running":
            return
        _preparing[language] = {"state": "running", "error": None}

    def run() -> None:
        try:
            prepare_corpus(language)
            _preparing[language] = {"state": "done", "error": None}
        except Exception as exc:  # noqa: BLE001
            _preparing[language] = {"state": "error", "error": str(exc)}

    threading.Thread(target=run, daemon=True).start()


def load_corpus(language: str) -> tuple[list[dict[str, str]], str]:
    """Returns (prompts, source) where source is "corpus" or "builtin" (while the corpus is being prepared)."""
    path = corpus_path(language)
    if path.exists():
        try:
            return json.loads(path.read_text()), "corpus"
        except json.JSONDecodeError:
            path.unlink(missing_ok=True)
    if _preparing.get(language, {}).get("state") != "error" and not os.environ.get("VT_OFFLINE"):
        _prepare_in_background(language)
    return [{"id": prompt_id(s), "text": s} for s in BUILTIN.get(language, BUILTIN["en"])], "builtin"


def custom_path(voice: Voice):
    return voice.dir / "custom_prompts.json"


def load_custom(voice: Voice) -> list[dict[str, str]]:
    path = custom_path(voice)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.?!])\s+|\n+", text)
    out = []
    for part in parts:
        s = _clean(part)
        if len(s) >= 8 and len(s.split()) >= 2:
            out.append(s[:300])
    return out


def add_custom(voice: Voice, text: str) -> int:
    """Queues the sentences of ``text`` (in order) before everything else, so they are read next."""
    existing = load_custom(voice)
    ids = {p["id"] for p in existing}
    fresh = []
    for s in split_sentences(text):
        pid = prompt_id(s)
        if pid not in ids:
            fresh.append({"id": pid, "text": s})
            ids.add(pid)
    custom_path(voice).write_text(json.dumps(fresh + existing, ensure_ascii=False, indent=1))
    return len(fresh)


def all_prompts(voice: Voice) -> tuple[list[dict[str, str]], str]:
    settings = load_settings(voice)
    corpus, source = load_corpus(settings["language"])
    return load_custom(voice) + corpus, source


def next_prompts(voice: Voice, recorded_ids: set[str], count: int = 5) -> dict[str, Any]:
    settings = load_settings(voice)
    prompts, source = all_prompts(voice)
    skipped = set(settings.get("skipped_prompts") or [])
    remaining = [p for p in prompts if p["id"] not in recorded_ids and p["id"] not in skipped]
    return {
        "items": remaining[:count],
        "total": len(prompts),
        "remaining": len(remaining),
        "source": source,
        "preparing": _preparing.get(settings["language"]),
        "custom": len(load_custom(voice)),
    }


def skip_prompt(voice: Voice, pid: str) -> None:
    settings = load_settings(voice)
    skipped = list(settings.get("skipped_prompts") or [])
    if pid not in skipped:
        skipped.append(pid)
    settings["skipped_prompts"] = skipped[-5000:]
    write_settings(voice, settings)
