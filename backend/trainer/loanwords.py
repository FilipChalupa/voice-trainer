"""Czech loanwords and abbreviations that are not read the way they are written.

espeak reads Czech text letter by letter ("software" as "softvare", "jazz" as "jass", "USB" as "usp"), while a
speaker says "softvér", "džez", "ú es bé". Left alone, the training text and the recording disagree about the
sounds of such a word. `respell` rewrites them phonetically, in Czech spelling, before the text is turned into
phonemes: for the training transcripts, for what this app synthesises and on both sides of the Whisper check.

Only words with one settled Czech pronunciation are listed; a word people say two ways (router, wi-fi) is left
to the voice's own lexicon. Standard library only: the Whisper worker imports this file too.
"""
from __future__ import annotations

import re

# endings a borrowed masculine noun and its adjective take: softwaru, e-mailem, jazzový
_M = r"(?:u|e|em|y|ů|ům|ech|a|i|ovi|ové|ový|ová|ovou|ového|ovém|ových|ovým|ově)?"
# a feminine noun in -a, listed by its stem: pizza, pizzu, pizzerie
_F = r"(?:a|u|y|e|ou|ám|ách|ami|erie|erii|erií)"
_X = ""  # only the form as written
_ANY = r"\w*"  # a stem: whatever follows belongs to the same word (technika, technický, technikou)

# written, spoken, endings
_CS: list[tuple[str, str, str]] = [
    # computers and the office
    ("software", "softvér", _X), ("softwar", "softvér", _M),
    ("hardware", "hardvér", _X), ("hardwar", "hardvér", _M),
    ("e-mail", "ímejl", _M), ("email", "ímejl", _M), ("mail", "mejl", _M),
    ("notebook", "noutbuk", _M), ("display", "displej", _M), ("browser", "brauzr", _M),
    ("online", "onlajn", _X), ("offline", "oflajn", _X),
    ("update", "apdejt", _X), ("updat", "apdejt", _M),
    ("download", "daunloud", _M), ("upload", "aploud", _M),
    ("smartphone", "smartfoun", _X), ("smartphon", "smartfoun", _M),
    ("bluetooth", "blútús", _X), ("playlist", "plejlist", _M), ("streaming", "stríming", _M),
    ("podcast", "podkást", _M), ("chatbot", "četbot", _M), ("hacker", "hekr", _M), ("cache", "keš", _X),
    ("megabyte", "megabajt", _X), ("megabyt", "megabajt", _M), ("gigabyte", "gigabajt", _X), ("gigabyt", "gigabajt", _M),
    ("interface", "interfejs", _X), ("feedback", "fídbek", _M), ("workshop", "vorkšop", _M),
    ("meeting", "mítynk", _M), ("deadline", "dedlajn", _X), ("deadlin", "dedlajn", _M),
    ("management", "menedžment", _M), ("business", "byznys", _X), ("leasing", "lízink", _M),
    ("design", "dyzajn", _M), ("designér", "dyzajnér", _M), ("team", "tým", _M), ("know-how", "nou hau", _X),
    ("copyright", "kopyrajt", _M), ("image", "imidž", _X), ("interview", "intervjú", _X),
    # brands and services
    ("youtube", "jútjúb", _M), ("google", "gúgl", _X), ("googl", "gúgl", _M), ("facebook", "fejsbuk", _M),
    ("windows", "vindous", _X), ("microsoft", "majkrosoft", _M), ("iphone", "ajfoun", _X), ("iphon", "ajfoun", _M),
    ("spotify", "spotyfaj", _X), ("skype", "skajp", _X), ("zigbee", "zigbí", _X), ("home assistant", "houm asistent", _M),
    # food
    ("pizz", "pic", _F), ("juice", "džus", _M), ("sandwich", "sendvič", _M), ("ketchup", "kečup", _M),
    ("croissant", "kroasán", _M), ("whisky", "visky", _X), ("menu", "meny", _X),
    # culture, sport, society
    ("jazz", "džez", _M), ("show", "šou", _X), ("cool", "kúl", _X), ("thriller", "triler", _M),
    ("weekend", "víkend", _M), ("teenager", "týnejdžr", _M), ("dealer", "dýler", _M), ("outsider", "autsajdr", _M),
    ("cowboy", "kovboj", _M), ("skateboard", "skejtbórd", _M), ("snowboard", "snoubórd", _M),
    ("fair play", "fér plej", _X), ("happy end", "hepy end", _M),
    ("foyer", "foajé", _X), ("rendezvous", "randevú", _X), ("faux pas", "fó pa", _X), ("déjà vu", "dežaví", _X),
    ("new york", "ňú jork", _M), ("shakespeare", "šejkspír", _X), ("shakespear", "šejkspír", _M),
    ("flash", "fleš", _M),
    # hard "ti, di, ni" that espeak softens ("technika" as "techňika", "Martin" as "Marťin"): written with y
    ("technik", "technyk", _ANY), ("technic", "technyc", _ANY), ("tip", "typ", _ANY), ("tiket", "tyket", _ANY),
    ("dinosaur", "dynosaur", _ANY), ("martin", "martyn", _ANY), ("kristin", "kristyn", _ANY), ("kristián", "kristyján", _ANY),
    ("sebastian", "sebastyján", _ANY), ("tiráž", "tyráž", _ANY), ("latin", "latyn", _ANY), ("bandit", "bandyt", _ANY),
    ("pozitiv", "pozityv", _ANY), ("negativ", "negatyv", _ANY), ("festival", "festyval", _ANY), ("unikát", "unykát", _ANY),
    ("tunik", "tunyk", _ANY), ("artikl", "artykl", _ANY), ("nitrogl", "nytrogl", _ANY), ("nikaragu", "nykaragu", _ANY),
    ("senior", "senyjor", _ANY), ("junior", "junyjor", _ANY), ("daniel", "danyjel", _ANY), ("matild", "matyld", _ANY),
    ("judit", "judyt", _ANY), ("destinac", "destynac", _ANY), ("diviz", "dyviz", _ANY), ("dilema", "dylema", _ANY),
    ("identit", "identyt", _ANY), ("kvantit", "kvantyt", _ANY), ("entit", "entyt", _ANY), ("etnik", "etnyk", _ANY),
    ("etnic", "etnyc", _ANY), ("tinitus", "tynytus", _ANY), ("gardin", "gardyn", _ANY), ("pianin", "pianyn", _ANY),
    ("pudink", "pudynk", _ANY), ("mítink", "mítynk", _ANY), ("kondičn", "kondyčn", _ANY),
]

# abbreviations espeak does not spell out by itself (it does for most: SMS, DVD, GPS…); matched in capitals only,
# and written as one word, because a lone "ú" is read as the name of the letter
_CS_ABBREVIATIONS: list[tuple[str, str]] = [("USB", "úesbé"), ("WC", "vécé"), ("EU", "eú"), ("HDMI", "hádéemí")]


def _compile(entries: list[tuple[str, str, str]]) -> list[tuple[re.Pattern[str], str]]:
    # longest first: "e-mail" before "mail", "software" before "softwar" + ending
    ordered = sorted(entries, key=lambda e: len(e[0]), reverse=True)
    return [(re.compile(r"(?<![\w-])" + re.escape(written).replace(r"\ ", r"\s+") + "(" + endings + r")(?![\w-])", re.IGNORECASE), spoken) for written, spoken, endings in ordered]


_PATTERNS = {"cs": _compile(_CS)}
_ABBREVIATIONS = {"cs": [(re.compile(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])"), s) for a, s in sorted(_CS_ABBREVIATIONS, key=lambda e: len(e[0]), reverse=True)]}


# "vlk", "plst", "zvlhl": no vowel and no r, so espeak takes the word for an abbreviation and spells it. A syllabic
# mark (U+0329) after the first l makes it read the word.
_NO_VOWEL = re.compile(r"(?<![\w-])([bcčdďfghjkmnňpsštťvzž]*l)([bcčdďfghjklmnňpsštťvzž]+)(?![\w-])", re.IGNORECASE)


def respell(text: str, language: str = "cs", skip: set[str] | frozenset[str] = frozenset()) -> str:
    """Rewrites the listed words the way they are said. `skip` holds lower-case words to leave alone (the ones
    the voice's own lexicon handles). Languages without a list come back unchanged."""
    language = language.split("-")[0].split("_")[0]
    for pattern, spoken in _ABBREVIATIONS.get(language, []):
        text = pattern.sub(lambda m, s=spoken: m.group(0) if m.group(0).lower() in skip else s, text)

    def swap(m: re.Match[str], spoken: str) -> str:
        whole = m.group(0)
        if whole.lower() in skip or whole[: len(whole) - len(m.group(1))].lower() in skip:
            return whole
        out = spoken + m.group(1)
        return out[:1].upper() + out[1:] if whole[:1].isupper() else out

    for pattern, spoken in _PATTERNS.get(language, []):
        text = pattern.sub(lambda m, s=spoken: swap(m, s), text)
    if language == "cs":
        text = _NO_VOWEL.sub(lambda m: m.group(0) if m.group(0).isupper() or m.group(0).lower() in skip else f"{m.group(1)}\u0329{m.group(2)}", text)
    return text


_TOKENS = {"cs": {t for w, _, _ in _CS if " " in w for t in w.split()}}


def listed(word: str, language: str = "cs") -> bool:
    """True for a word the list knows (in any of its forms), alone or as a part of a listed phrase."""
    language = language.split("-")[0].split("_")[0]
    return word.lower() in _TOKENS.get(language, ()) or respell(word, language) != word


def entries(language: str = "cs") -> list[dict[str, str]]:
    """The base forms of the list, for showing in the app."""
    language = language.split("-")[0].split("_")[0]
    if language != "cs":
        return []
    words = [{"word": w + ("…" if e == _ANY else ""), "spoken": s + ("…" if e == _ANY else "")} for w, s, e in _CS if not any(w != o and o.startswith(w) and e not in (_X, _ANY) for o, _, _ in _CS)]
    return words + [{"word": a, "spoken": s} for a, s in _CS_ABBREVIATIONS]
