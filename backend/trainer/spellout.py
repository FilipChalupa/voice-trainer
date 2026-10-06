"""Czech numbers with units, clock times, dates and abbreviations written the way they are read aloud.

espeak reads "25 %" as "dvacet pět procento", "5 kWh" as "pět k dvojvé há", "3. května" as "tři května" and
"atd." letter by letter; a person reads "procent", "kilowatthodin", "třetího května", "a tak dále". `spell_out`
closes that gap before the text is turned into phonemes. Plain numbers stay digits (espeak reads those right);
only what espeak gets wrong is put into words. Standard library only: the Whisper worker imports this file too.
"""
from __future__ import annotations

import re

# unit: one, few (2-4), many, after a decimal, gender
_UNITS: dict[str, tuple[str, str, str, str, str]] = {
    "%": ("procento", "procenta", "procent", "procenta", "n"),
    "°C": ("stupeň Celsia", "stupně Celsia", "stupňů Celsia", "stupně Celsia", "m"),
    "°": ("stupeň", "stupně", "stupňů", "stupně", "m"),
    "Kč": ("koruna", "koruny", "korun", "koruny", "f"),
    "€": ("euro", "eura", "eur", "eura", "n"),
    "$": ("dolar", "dolary", "dolarů", "dolaru", "m"),
    "km/h": ("kilometr za hodinu", "kilometry za hodinu", "kilometrů za hodinu", "kilometru za hodinu", "m"),
    "m/s": ("metr za sekundu", "metry za sekundu", "metrů za sekundu", "metru za sekundu", "m"),
    "Mb/s": ("megabit za sekundu", "megabity za sekundu", "megabitů za sekundu", "megabitu za sekundu", "m"),
    "kWh": ("kilowatthodina", "kilowatthodiny", "kilowatthodin", "kilowatthodiny", "f"),
    "Wh": ("watthodina", "watthodiny", "watthodin", "watthodiny", "f"),
    "kW": ("kilowatt", "kilowatty", "kilowattů", "kilowattu", "m"),
    "MW": ("megawatt", "megawatty", "megawattů", "megawattu", "m"),
    "W": ("watt", "watty", "wattů", "wattu", "m"),
    "V": ("volt", "volty", "voltů", "voltu", "m"),
    "A": ("ampér", "ampéry", "ampérů", "ampéru", "m"),
    "Hz": ("hertz", "hertzy", "hertzů", "hertzu", "m"),
    "kHz": ("kilohertz", "kilohertzy", "kilohertzů", "kilohertzu", "m"),
    "MHz": ("megahertz", "megahertzy", "megahertzů", "megahertzu", "m"),
    "hPa": ("hektopaskal", "hektopaskaly", "hektopaskalů", "hektopaskalu", "m"),
    "dB": ("decibel", "decibely", "decibelů", "decibelu", "m"),
    "lx": ("lux", "luxy", "luxů", "luxu", "m"),
    "GB": ("gigabajt", "gigabajty", "gigabajtů", "gigabajtu", "m"),
    "MB": ("megabajt", "megabajty", "megabajtů", "megabajtu", "m"),
    "kB": ("kilobajt", "kilobajty", "kilobajtů", "kilobajtu", "m"),
    "TB": ("terabajt", "terabajty", "terabajtů", "terabajtu", "m"),
    "km": ("kilometr", "kilometry", "kilometrů", "kilometru", "m"),
    "m": ("metr", "metry", "metrů", "metru", "m"),
    "cm": ("centimetr", "centimetry", "centimetrů", "centimetru", "m"),
    "mm": ("milimetr", "milimetry", "milimetrů", "milimetru", "m"),
    "kg": ("kilogram", "kilogramy", "kilogramů", "kilogramu", "m"),
    "g": ("gram", "gramy", "gramů", "gramu", "m"),
    "l": ("litr", "litry", "litrů", "litru", "m"),
    "ml": ("mililitr", "mililitry", "mililitrů", "mililitru", "m"),
    "dl": ("decilitr", "decilitry", "decilitrů", "decilitru", "m"),
    "min": ("minuta", "minuty", "minut", "minuty", "f"),
    "ms": ("milisekunda", "milisekundy", "milisekund", "milisekundy", "f"),
    "ks": ("kus", "kusy", "kusů", "kusu", "m"),
}
_UNIT_RE = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
# "5 min. denně": the full stop of an abbreviated unit goes with it, unless it closes the sentence
_QUANTITY = re.compile(r"(?<![\w,.:])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:,(\d+))?[   ]?(" + _UNIT_RE + r")(?![\w/°])(?:\.(?=\s+[a-zá-ž\d]))?")
_DECIMAL = re.compile(r"(?<![\w,.:])(\d{1,3}(?:[   ]\d{3})+|\d+),(\d+)(?![\d,])")
_THOUSANDS = re.compile(r"(?<![\w,.:])\d{1,3}(?:[   ]\d{3})+(?![\w,])")
_CLOCK = re.compile(r"(?:(?<=\s)|^)(v |ve )?([01]?\d|2[0-3]):([0-5]\d)(?![\d:])", re.IGNORECASE)
_RANGE = re.compile(r"(?<=\d)[ ]?[–-][ ]?(?=\d)")

_MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"]
_ORDINALS = [
    "prvního", "druhého", "třetího", "čtvrtého", "pátého", "šestého", "sedmého", "osmého", "devátého", "desátého",
    "jedenáctého", "dvanáctého", "třináctého", "čtrnáctého", "patnáctého", "šestnáctého", "sedmnáctého", "osmnáctého",
    "devatenáctého", "dvacátého",
]
_DATE_WORD = re.compile(r"(?<![\w.])(\d{1,2})\.[  ]?(" + "|".join(_MONTHS) + r")(?!\w)")
_DATE_DIGITS = re.compile(r"(?<![\w.])(\d{1,2})\.[  ]?(\d{1,2})\.(?:[  ]?(\d{4}))?(?![\w])")

# abbreviation -> words; True = it may close a sentence, then the full stop is kept
_ABBREVIATIONS: list[tuple[str, str, bool]] = [
    ("s. r. o.", "eseró", True), ("a. s.", "akciová společnost", True), ("č. p.", "číslo popisné", False),
    ("na str.", "na straně", False), ("na obr.", "na obrázku", False), ("v kap.", "v kapitole", False), ("v tab.", "v tabulce", False),
    ("např.", "například", False), ("atd.", "a tak dále", True), ("apod.", "a podobně", True), ("atp.", "a tak podobně", True),
    ("aj.", "a jiné", True), ("tzv.", "takzvaný", False), ("tj.", "to jest", False), ("tzn.", "to znamená", False),
    ("mj.", "mimo jiné", False), ("resp.", "respektive", False), ("popř.", "popřípadě", False), ("příp.", "případně", False),
    ("vč.", "včetně", False), ("cca", "cirka", False), ("č.", "číslo", False), ("str.", "strana", False),
    ("tel.", "telefon", False), ("max.", "maximálně", False), ("min.", "minimálně", False),
    ("kap.", "kapitola", False), ("obr.", "obrázek", False), ("tab.", "tabulka", False), ("pozn.", "poznámka", False),
    ("tis.", "tisíc", False), ("mil.", "milionů", False), ("mld.", "miliard", False), ("hod.", "hodin", True),
    ("nám.", "náměstí", False), ("stol.", "století", True), ("vs.", "versus", False),
    ("Ing.", "inženýr", False), ("MUDr.", "doktor", False), ("JUDr.", "doktor", False), ("PhDr.", "doktor", False),
    ("RNDr.", "doktor", False), ("MVDr.", "doktor", False), ("Mgr.", "magistr", False), ("Bc.", "bakalář", False),
    ("doc.", "docent", False), ("prof.", "profesor", False),
]
def _abbreviation_re(a: str) -> re.Pattern[str]:
    # "např." also as "Např." at the start of a sentence; titles (Ing., MUDr.) only as written
    first = f"[{a[0]}{a[0].upper()}]" if a[0].islower() else re.escape(a[0])
    return re.compile(r"(?<![\w.])" + first + re.escape(a[1:]).replace(r"\ ", r"[  ]?") + (r"(?!\w)" if a.endswith(".") else r"(?![\w.])"))


_ABBREVIATION_RES = [(_abbreviation_re(a), words, closes, a[0].islower()) for a, words, closes in sorted(_ABBREVIATIONS, key=lambda e: len(e[0]), reverse=True)]


def _ordinal(day: int) -> str:
    if day <= 20:
        return _ORDINALS[day - 1]
    tens = "dvacátého" if day < 30 else "třicátého"
    return tens if day % 10 == 0 else f"{tens} {_ORDINALS[day % 10 - 1]}"


def _number(n: int, gender: str) -> str:
    """The number as espeak should read it: digits, except where "jeden/dva" must agree with the noun."""
    if n % 100 in (11, 12) or n % 10 not in (1, 2):
        return str(n)
    if n < 10:
        return {("f", 1): "jedna", ("n", 1): "jedno", ("m", 1): "jeden", ("m", 2): "dva"}.get((gender, n), "dvě")
    if gender == "m":
        return str(n)
    # 22 hodiny, 21 korun: "20 dvě" is read "dvacet dvě", "20 jedna" "dvacet jedna" (espeak alone says "dvacet jeden")
    return f"{n - n % 10} {'jedna' if n % 10 == 1 else 'dvě'}"


def _form(n: int) -> int:
    if n == 1:
        return 0
    return 1 if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 2


def _decimal(whole: int, fraction: str) -> str:
    """23,5 -> "23 celé 5", 0,05 -> "0 celá 0 5", 1,5 -> "jedna celá 5"."""
    if whole % 100 in (11, 12, 13, 14):
        word = "celých"
    else:
        word = "celá" if whole % 10 == 1 or whole == 0 else "celé" if whole % 10 in (2, 3, 4) else "celých"
    zeros = len(fraction) - len(fraction.lstrip("0"))
    rest = fraction.lstrip("0")
    return f"{_number(whole, 'f')} {word} {' '.join(['0'] * zeros + ([rest] if rest else []))}"


def _digits(group: str) -> int:
    return int(re.sub(r"\D", "", group))


def spell_out(text: str, language: str = "cs") -> str:
    """Rewrites what espeak would read differently from a person. Other languages come back unchanged."""
    if language.split("-")[0].split("_")[0] != "cs" or not re.search(r"\d|\.|cca", text):
        return text

    def date_word(m: re.Match[str]) -> str:
        day = int(m.group(1))
        return f"{_ordinal(day)} {m.group(2)}" if 1 <= day <= 31 else m.group(0)

    def date_digits(m: re.Match[str]) -> str:
        day, month = int(m.group(1)), int(m.group(2))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return m.group(0)
        out = f"{_ordinal(day)} {_MONTHS[month - 1]}"
        if m.group(3):
            return f"{out} {m.group(3)}"
        # the second full stop was the date's; at the end of the text it also closed the sentence
        return out + ("." if m.end() == len(m.string) else "")

    def clock(m: re.Match[str]) -> str:
        prefix, hour, minute = m.group(1) or "", int(m.group(2)), m.group(3)
        if minute == "00":
            if hour == 1:
                return f"{prefix[:1]} jednu hodinu" if prefix else "jedna hodina"
            return f"{prefix}{_number(hour, 'f')} {('hodina', 'hodiny', 'hodin')[_form(hour)]}"
        spoken = f"0 {minute[1]}" if minute[0] == "0" else minute
        return f"{prefix}{_number(hour, 'f')} {spoken}"

    def quantity(m: re.Match[str]) -> str:
        whole, fraction, unit = _digits(m.group(1)), m.group(2), _UNITS[m.group(3)]
        if fraction:
            return f"{_decimal(whole, fraction)} {unit[3]}"
        return f"{_number(whole, unit[4])} {unit[_form(whole)]}"

    text = _DATE_WORD.sub(date_word, text)
    text = _DATE_DIGITS.sub(date_digits, text)
    text = _CLOCK.sub(clock, text)
    text = _RANGE.sub(" až ", text)
    text = _QUANTITY.sub(quantity, text)
    text = _DECIMAL.sub(lambda m: _decimal(_digits(m.group(1)), m.group(2)), text)
    text = _THOUSANDS.sub(lambda m: str(_digits(m.group(0))), text)
    for pattern, words, closes, lower in _ABBREVIATION_RES:
        def expand(m: re.Match[str], words: str = words, closes: bool = closes, lower: bool = lower) -> str:
            after = m.string[m.end():]
            ends = closes and (not after.strip() or re.match(r"\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]", after) is not None)
            # "Např." opens a sentence and keeps its capital; a title (Ing.) is always written with one
            out = words[:1].upper() + words[1:] if m.group(0)[:1].isupper() and lower else words
            return out + ("." if ends else "")

        text = pattern.sub(expand, text)
    return text


_DIGITS = re.compile(r"\d+")
_MINUS = re.compile(r"(?<![\w])[-−](?=\d)")  # "-3 °C" is said "mínus tři"


def in_words(text: str, language: str = "cs") -> str:
    """`spell_out` plus the remaining numbers in words: what a person is to read ("v šest čtyřicet pět"), and
    what the length check counts. espeak gets the digits, it reads those right by itself."""
    language = language.split("-")[0].split("_")[0]
    text = spell_out(text, language)
    try:
        from num2words import num2words
    except ImportError:  # pragma: no cover
        return text
    text = _MINUS.sub("mínus ", text)
    return _DIGITS.sub(lambda m: num2words(int(m.group(0)), lang=language) if len(m.group(0)) < 10 else m.group(0), text)
