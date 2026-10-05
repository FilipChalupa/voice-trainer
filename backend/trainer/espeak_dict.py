"""A Czech espeak-ng dictionary that reads loanwords the way they are said, for players without this app.

Piper in Home Assistant turns text into phonemes with espeak-ng and nothing else: no lexicon, no respelling.
espeak-ng reads its pronunciation rules from one compiled file per language (`cs_dict`), so the knowledge of
`loanwords.py` can be compiled into that file and mounted into the Piper container. Then "software", "Martin"
or "vlk" come out right for any text, whoever sends it.

What goes in:
- hard "ti, di, ni" stems as rules in the groups espeak already has for them,
- loanword stems as rules (a rule also works after a preposition, which espeak joins to the next word with a
  hyphen; a word-list entry does not), in their word-final and inflected form,
- phrases and hyphenated words as word-list entries (they cannot be rules, so after "do", "na"… they fall
  back to the words they are made of),
- vowel-less words and abbreviations as phoneme entries,
- the voice's own lexicon.

Numbers with units, times and dates are not here: a dictionary cannot inflect by a number. The phonemes of
every entry come from espeak itself, read from the respelling this app already uses, so both paths agree.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .loanwords import _ANY, _CS, _CS_ABBREVIATIONS, _F, _M, _X

# endings generated for word-list entries (phrases); rules need none, the rest of the word is read normally
_M_ENDINGS = ["u", "e", "em", "y", "ů", "ům", "ech", "a", "i", "ovi", "ové"]
_VOWELLESS = ["vlk", "plk", "plž", "mlž", "blb", "plst", "mlč", "plň", "pln", "vln", "slz", "žlč", "mlh", "vlh", "zvlhl", "zmlkl", "zhltl", "hlt", "splň"]
_SOFT = {"t": "ti", "d": "di", "n": "ni"}
# The words of the listed phrases, where they are safe on their own: a phrase is a word-list entry, which does
# not apply after a preposition, and then its words are read one by one. (word, respelling, takes endings)
_PHRASE_WORDS = [("home", "houm", False), ("assistant", "asistent", True), ("fair", "fér", False), ("play", "plej", False), ("happy", "hepy", False),
                 ("faux", "fó", False), ("déjà", "deža", False), ("york", "jork", True), ("know", "nou", False), ("how", "hau", False)]


class DictionaryError(RuntimeError):
    pass


def find_tools() -> tuple[Path, Path, Path]:
    """The espeak-ng compiler, the dictionary sources and the data Piper was built with (they sit in Piper's
    build tree inside the app image)."""
    import piper

    data = Path(piper.__file__).parent / "espeak-ng-data"
    for root in [Path(piper.__file__).parents[2], Path("/opt/piper")]:
        binaries = sorted(root.glob("_skbuild/*/cmake-build/espeak_ng/src/espeak_ng_external-build/src/espeak-ng"))
        sources = sorted(root.glob("_skbuild/*/cmake-build/espeak_ng/src/espeak_ng_external/dictsource"))
        if binaries and sources and data.exists():
            return binaries[0], sources[0], data
    raise DictionaryError("espeak-ng with its dictionary sources is not available here")


def _phonemes(binary: Path, data_parent: Path, texts: list[str]) -> list[str]:
    """espeak's own phoneme names for each text, stress marks left to the rules."""
    out = []
    for text in texts:
        proc = subprocess.run([str(binary), f"--path={data_parent}", "-v", "cs", "-q", "-x", text], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise DictionaryError(proc.stderr.strip() or "espeak-ng failed")
        out.append(re.sub(r"[',\s_]", "", proc.stdout))
    return out


def _hard_positions(written: str, spoken: str) -> list[int]:
    """Indexes of the t/d/n in `written` whose following "i" is hard (the respelling has "y" there)."""
    found, j = [], 0
    for i, ch in enumerate(written):
        while j < len(spoken) and spoken[j] == "j" and ch != "j":
            j += 1  # a glide the respelling adds: senior -> senyjor
        if j < len(spoken) and ch == "i" and spoken[j] == "y" and i > 0 and written[i - 1] in _SOFT:
            found.append(i - 1)
        j += 1
    return found


def build_sources(binary: Path, dictsource: Path, data_parent: Path, lexicon: dict[str, str] | None = None) -> tuple[str, str]:
    """The text to append to cs_extra (word list) and the rules to merge into cs_rules: (list, {group: lines})."""
    # a rule is tried at the start of a word ("_") and after a hyphen: espeak joins a short word to the
    # preposition before it with one ("do-softwaru"), and reads the pair as a single word
    starts = ["_", "-"]
    listing: list[str] = []
    rules: dict[str, list[str]] = {}

    def rule(group: str, pre: str, match: str, post: str, phonemes: str) -> None:
        for start in starts:
            rules.setdefault(group, []).append(f"{start}{pre}) {match} {'(' + post + ' ' if post else ''}{phonemes}")

    def word(written: str, spoken: str, inflects: bool) -> None:
        """A single word: its word-final form, and its stem for whatever ending follows."""
        final = _phonemes(binary, data_parent, [spoken])[0]
        rule(written[0], "", written, "_", final)
        if inflects:
            stem = _phonemes(binary, data_parent, [spoken + "u"])[0]
            if stem.endswith("u"):
                rule(written[0], "", written, "", stem[:-1])

    def phrase(written: str, spoken: str, endings: list[str]) -> None:
        for ending in ["", *endings]:
            listing.append(f"({written}{ending}) {spoken}{ending} $text")

    for written, spoken, endings in _CS:
        if endings == _ANY:
            for i in _hard_positions(written, spoken):
                rule(_SOFT[written[i]], written[:i], _SOFT[written[i]], written[i + 2 : i + 5], _SOFT[written[i]])
        elif " " in written or "-" in written:
            phrase(written, spoken, _M_ENDINGS if endings == _M else [])
        else:
            word(written, spoken, endings in (_M, _F))
    for written, spoken, inflects in _PHRASE_WORDS:
        word(written, spoken, inflects)
    # "e-mail" after a preposition: the list entry does not apply, "mail" has its rule, the "e" is said "í"
    rule("e", "", "e", "-mail", "i:")
    # a capital inside a word makes espeak read two words: YouTube -> "You Tube", iPhone -> "i Phone"
    for first, second, spoken in (("you", "tube", "jútjúb"), ("i", "phone", "ajfoun")):
        phrase(f"{first} {second}", spoken, [])
        phrase(f"{first} {second[:-1]}", spoken, ["u", "em"])
    for written, spoken in (("you", "jú"), ("tube", "tjúb")):  # the same two after a preposition
        word(written, spoken, False)
    for written, spoken in _CS_ABBREVIATIONS:
        final = _phonemes(binary, data_parent, [spoken])[0]
        listing.append(f"{written.lower()} {final} $abbrev")
        rule(written[0].lower(), "", written.lower(), "_", final)
    for written, final in zip(_VOWELLESS, _phonemes(binary, data_parent, [re.sub("l", "l̩", w, count=1) for w in _VOWELLESS])):
        listing.append(f"{written} {final}")
    for written, spoken in (lexicon or {}).items():
        written, spoken = " ".join(written.lower().split()), " ".join(spoken.split())
        if not written or not spoken or written == spoken.lower():
            continue
        if re.fullmatch(r"[^\W\d_]+", written) and " " not in spoken:
            word(written, spoken, False)
        elif re.fullmatch(r"[^\W\d_]+(?:[ -][^\W\d_]+){0,3}", written):
            phrase(written, spoken, [])
    return "\n".join(listing) + "\n", rules  # type: ignore[return-value]


def merge_rules(source: str, rules: dict[str, list[str]]) -> str:
    """Puts each rule into the group of its first letters: the two-letter group when the language has one."""
    groups = set(re.findall(r"^\.group[ \t]+(\S+)", source, flags=re.MULTILINE))
    extra: dict[str, list[str]] = {}
    for group, lines in rules.items():
        for line in lines:
            match = line.split(") ", 1)[1].split()[0]
            target = match[:2] if match[:2] in groups else group
            extra.setdefault(target, []).append(line)
    out = source.rstrip("\n") + "\n"
    for group, lines in extra.items():
        block = "".join(f"        {line}\n" for line in dict.fromkeys(lines))
        marker = re.search(rf"^\.group[ \t]+{re.escape(group)}[ \t]*$", out, flags=re.MULTILINE)
        if marker:
            out = out[: marker.end()] + "\n" + block + out[marker.end() + 1 :]
        else:
            out += f"\n.group {group}\n{block}"
    return out


def cache_key(lexicon: dict[str, str] | None = None) -> str:
    """Changes whenever the built-in list, the generator or the lexicon does."""
    import hashlib
    import json

    payload = json.dumps([_CS, _CS_ABBREVIATIONS, _VOWELLESS, _PHRASE_WORDS, sorted((lexicon or {}).items()), Path(__file__).read_text(encoding="utf-8")], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def build(target: Path, lexicon: dict[str, str] | None = None) -> Path:
    """Compiles the Czech dictionary with this app's pronunciations into `target` (a file path) and returns it."""
    binary, dictsource, data = find_tools()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(data, work / "espeak-ng-data")
        shutil.copytree(dictsource, work / "dictsource")
        listing, rules = build_sources(binary, dictsource, work, lexicon)
        (work / "dictsource" / "cs_extra").write_text(listing, encoding="utf-8")
        rules_file = work / "dictsource" / "cs_rules"
        rules_file.write_text(merge_rules(rules_file.read_text(encoding="utf-8"), rules), encoding="utf-8")  # type: ignore[arg-type]
        proc = subprocess.run([str(binary), f"--path={work}", "--compile=cs"], cwd=work / "dictsource", capture_output=True, text=True, timeout=120)
        compiled = work / "espeak-ng-data" / "cs_dict"
        if proc.returncode != 0 or "rror" in proc.stdout + proc.stderr or not compiled.exists():
            raise DictionaryError((proc.stdout + proc.stderr).strip()[-600:] or "the dictionary did not compile")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(compiled, target)
    return target
