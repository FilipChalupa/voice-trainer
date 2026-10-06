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

from trainer.spellout import in_words

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


DICTIONARY_FILES = {"cs": "cs_CZ", "en": "en_US"}
_dictionaries: dict[str, Any] = {}
_WORD = re.compile(r"[^\W\d_]+")


def _dictionary(language: str):
    """Hunspell dictionary of the language (pure Python, loads in about a second), None when unavailable."""
    if language not in _dictionaries:
        try:
            from spylls.hunspell import Dictionary

            base = os.path.join(os.path.dirname(__file__), "dictionaries", DICTIONARY_FILES[language])
            _dictionaries[language] = Dictionary.from_files(base)
        except Exception:  # noqa: BLE001  (no dictionary = no spell filtering, not an error)
            _dictionaries[language] = None
    return _dictionaries[language]


def misspelled(sentence: str, language: str) -> list[str]:
    """Lowercase words the dictionary does not know: typos, slang and archaic forms. Names are capitalised and
    therefore not checked. Empty when no dictionary is available."""
    d = _dictionary(language)
    if d is None:
        return []
    return [w for w in _WORD.findall(sentence) if w.islower() and len(w) > 1 and not d.lookup(w)]


def filter_sentences(lines: list[str], language: str, spell: bool = True) -> list[str]:
    """Keeps natural, readable sentences: 6-16 words, 35-120 characters, only the language's alphabet and, with a
    dictionary at hand, no misspelled words (a typo in a prompt would be read aloud and kept as the transcript)."""
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
        if spell and misspelled(s, language):
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


CORPUS_VERSION = 2  # bump when the filtering changes, so an already prepared corpus is rebuilt


def corpus_path(language: str):
    return PROMPTS_DIR / f"{language}.v{CORPUS_VERSION}.json"


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


# a full stop after these does not end a sentence (titles, common abbreviations), nor after an initial
ABBREVIATIONS = {
    "dr", "ing", "mgr", "bc", "prof", "doc", "mudr", "judr", "phdr", "p", "pí", "sl", "např", "tzv", "tj", "atd", "apod", "č", "čl", "sv", "st",
    "resp", "popř", "cca", "ul", "nám", "tzn", "mj", "tis", "mil", "str", "kpt", "por", "gen", "plk", "npor", "ppor",
    "mr", "mrs", "ms", "jr", "sr", "vs", "etc", "e.g", "i.e", "no", "vol", "ch", "fig", "col", "capt", "lt", "sgt", "rev", "hon",
}
_SENTENCE_END = re.compile(r"(?:(?<=[.?!…])|(?<=[.?!…][\"'”’)]))\s+(?=[„\"'“(]?[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ0-9])|\n+")


def split_sentences(text: str) -> list[str]:
    """Sentences of a text: a sentence ends with . ? ! followed by a capital, unless the dot belongs to an
    abbreviation, an initial or a date ("dr. Mejzlík", "K. Čapek", "1. 5. 2026")."""
    out: list[str] = []
    pending = ""
    parts = [p for p in _SENTENCE_END.split(text.replace("\r", "")) if p and p.strip()]
    for i, part in enumerate(parts):
        candidate = (pending + " " + part).strip() if pending else part.strip()
        last = candidate.rstrip("\"'”’)").split()[-1] if candidate.split() else ""
        word = last.rstrip(".").lower()
        # "1. 5. 2026": the day of a date is followed by more of the date, not by a new sentence
        date = re.fullmatch(r"\d{1,2}\.", last) is not None and i + 1 < len(parts) and parts[i + 1].lstrip()[:1].isdigit()
        if last.endswith(".") and (date or word in ABBREVIATIONS or (len(word) == 1 and word.isalpha())):
            pending = candidate
            continue
        pending = ""
        s = _clean(candidate)
        if len(s) >= 8 and len(s.split()) >= 2:
            out.append(s[:300])
    if pending:
        s = _clean(pending)
        if len(s) >= 8 and len(s.split()) >= 2:
            out.append(s[:300])
    return out


def add_custom(voice: Voice, text: str, source: str | None = None) -> int:
    """Queues the sentences of ``text`` (in order) before everything else, so they are read next. ``source``
    names where they came from (a paragraph, a chapter, pasted text) so a batch can be removed again."""
    existing = load_custom(voice)
    ids = {p["id"] for p in existing}
    fresh = []
    for s in split_sentences(text):
        pid = prompt_id(s)
        if pid not in ids:
            fresh.append({"id": pid, "text": s, **({"source": source} if source else {})})
            ids.add(pid)
    custom_path(voice).write_text(json.dumps(fresh + existing, ensure_ascii=False, indent=1))
    return len(fresh)


def custom_batches(voice: Voice, recorded_ids: set[str]) -> list[dict[str, Any]]:
    """The queued custom sentences grouped by where they came from, with how many still wait to be read."""
    groups: dict[str, dict[str, Any]] = {}
    for p in load_custom(voice):
        key = p.get("source") or ""
        g = groups.setdefault(key, {"source": key, "total": 0, "remaining": 0})
        g["total"] += 1
        if p["id"] not in recorded_ids:
            g["remaining"] += 1
    return list(groups.values())


def remove_custom(voice: Voice, source: str | None, recorded_ids: set[str]) -> int:
    """Drops the unread custom sentences of one source (``None`` = of every source). Recorded ones stay, their
    takes keep pointing at them."""
    existing = load_custom(voice)
    kept = [p for p in existing if p["id"] in recorded_ids or (source is not None and (p.get("source") or "") != source)]
    custom_path(voice).write_text(json.dumps(kept, ensure_ascii=False, indent=1))
    return len(existing) - len(kept)


def all_prompts(voice: Voice) -> tuple[list[dict[str, str]], str]:
    settings = load_settings(voice)
    corpus, source = load_corpus(settings["language"])
    return load_custom(voice) + corpus, source


def next_prompts(voice: Voice, recorded_ids: set[str], count: int = 5) -> dict[str, Any]:
    settings = load_settings(voice)
    prompts, source = all_prompts(voice)
    skipped = set(settings.get("skipped_prompts") or [])
    seen: set[str] = set()
    remaining = [p for p in prompts if p["id"] not in recorded_ids and p["id"] not in skipped and not (p["id"] in seen or seen.add(p["id"]))]
    items = []
    for p in remaining[:count]:
        # numbers, units, dates and abbreviations in words: the reader sees what the transcript will hold
        read_as = in_words(p["text"], settings["language"])
        items.append({**p, "read_as": read_as} if read_as != p["text"] else p)
    return {
        "items": items,
        "total": len(prompts),
        "remaining": len(remaining),
        "source": source,
        "preparing": _preparing.get(settings["language"]),
        "custom": len(load_custom(voice)),
    }


def queue_front(voice: Voice, text: str) -> str:
    """Puts one sentence at the very front of the reading queue (added as a custom prompt if it is not one yet,
    moved if it is) and clears a skip of it. Returns the prompt id."""
    pid = prompt_id(text)
    current = load_custom(voice)
    mine = next((p for p in current if p["id"] == pid), {"id": pid, "text": text})
    existing = [p for p in current if p["id"] != pid]
    custom_path(voice).write_text(json.dumps([mine] + existing, ensure_ascii=False, indent=1))
    settings = load_settings(voice)
    skipped = [x for x in (settings.get("skipped_prompts") or []) if x != pid]
    if len(skipped) != len(settings.get("skipped_prompts") or []):
        settings["skipped_prompts"] = skipped
        write_settings(voice, settings)
    return pid


def skip_prompt(voice: Voice, pid: str) -> None:
    settings = load_settings(voice)
    skipped = list(settings.get("skipped_prompts") or [])
    if pid not in skipped:
        skipped.append(pid)
    settings["skipped_prompts"] = skipped[-5000:]
    write_settings(voice, settings)
