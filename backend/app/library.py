"""Longer texts to read in order: public-domain books from Wikisource / Project Gutenberg, any web page or
pasted text. The sentences are queued at the front like custom prompts."""
from __future__ import annotations

import html
import re
import threading
import time
from typing import Any

import requests
from fastapi import APIRouter, HTTPException

from . import prompts
from .config import load_settings
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["library"])

USER_AGENT = "voice-trainer/0.2 (https://github.com/FilipChalupa/voice-trainer)"
MAX_SENTENCES = 2000
MAX_BYTES = 3_000_000

# Books in the public domain (authors dead for more than 70 years), in today's spelling where possible.
BOOKS: dict[str, list[dict[str, Any]]] = {
    "cs": [
        {"id": "capek-jedna-kapsa", "title": "Povídky z jedné kapsy", "author": "Karel Čapek", "source": "wikisource", "site": "cs", "prefix": "Povídky z jedné kapsy/"},
        {"id": "capek-druha-kapsa", "title": "Povídky z druhé kapsy", "author": "Karel Čapek", "source": "wikisource", "site": "cs", "prefix": "Povídky z druhé kapsy/"},
        {"id": "hasek-svejk", "title": "Osudy dobrého vojáka Švejka za světové války", "author": "Jaroslav Hašek", "source": "wikisource", "site": "cs", "prefix": "Osudy dobrého vojáka Švejka za světové války/"},
        {"id": "nemcova-babicka", "title": "Babička", "author": "Božena Němcová", "source": "wikisource", "site": "cs", "prefix": "Babička/"},
    ],
    "en": [
        {"id": "carroll-alice", "title": "Alice's Adventures in Wonderland", "author": "Lewis Carroll", "source": "gutenberg", "url": "https://www.gutenberg.org/cache/epub/11/pg11.txt"},
        {"id": "doyle-holmes", "title": "The Adventures of Sherlock Holmes", "author": "Arthur Conan Doyle", "source": "gutenberg", "url": "https://www.gutenberg.org/cache/epub/1661/pg1661.txt"},
        {"id": "baum-oz", "title": "The Wonderful Wizard of Oz", "author": "L. Frank Baum", "source": "gutenberg", "url": "https://www.gutenberg.org/cache/epub/55/pg55.txt"},
    ],
}

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: str, ttl: float, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def _get(url: str, params: dict[str, str] | None = None) -> requests.Response:
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
    resp.raise_for_status()
    body = b""
    for chunk in resp.iter_content(chunk_size=65536):
        body += chunk
        if len(body) > MAX_BYTES:
            raise HTTPException(400, {"code": "too_large", "message": "The text is too large"})
    resp._content = body  # noqa: SLF001
    return resp


# ----- text cleaning -----
def strip_wikitext(text: str) -> str:
    """Plain prose out of MediaWiki markup: templates, links, formatting, headings, references, tables."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<(poem|noinclude|includeonly)[^>]*>.*?</\1>", "", text, flags=re.S)
    for _ in range(4):  # nested templates
        text = re.sub(r"\{\{(?:[^{}]|\{[^{}]*\})*\}\}", "", text, flags=re.S)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    text = re.sub(r"^=+.*?=+\s*$", "", text, flags=re.M)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^[*#:;]+\s*", "", text, flags=re.M)
    text = html.unescape(text)
    return text


def strip_gutenberg(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\[Illustration[^\]]*\]", "", text)
    start = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", text, flags=re.I)
    end = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK", text, flags=re.I)
    if end:
        text = text[: end.start()]
    if start:
        text = text[start.end() :]
    # unwrap hard-wrapped lines inside paragraphs
    return re.sub(r"(?<!\n)\n(?!\n)", " ", text)


def strip_html(text: str) -> str:
    text = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    text = re.sub(r"</(p|div|h\d|li|br|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def sentences_of(text: str) -> list[str]:
    out = []
    for s in prompts.split_sentences(text):
        if s.isupper() or len(s) > 300:
            continue
        out.append(s)
    return out[:MAX_SENTENCES]


_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _chapter_key(title: str) -> tuple[int, str]:
    """Chapters sorted by their number when the title starts with one (Roman or Arabic), otherwise by name."""
    head = re.match(r"^([IVXLC]+|\d+)\b", title.strip())
    if not head:
        return (10**6, title)
    token = head.group(1)
    if token.isdigit():
        return (int(token), title)
    total = 0
    for i, ch in enumerate(token):
        value = _ROMAN[ch]
        total += -value if i + 1 < len(token) and _ROMAN[token[i + 1]] > value else value
    return (total, title)


# ----- sources -----
def wikisource_chapters(site: str, prefix: str) -> list[dict[str, str]]:
    def fetch():
        resp = _get(f"https://{site}.wikisource.org/w/api.php", {"action": "query", "list": "prefixsearch", "pslimit": "100", "format": "json", "pssearch": prefix})
        titles = [x["title"] for x in resp.json()["query"]["prefixsearch"] if x["title"] != prefix.rstrip("/")]
        # subpages of chapters (e.g. "Book/Chapter/Part") stay out; the chapter page itself may hold the text
        chapters = [t for t in titles if t.count("/") == prefix.count("/")]
        return [{"page": t, "title": t[len(prefix) :]} for t in sorted(chapters, key=lambda t: _chapter_key(t[len(prefix) :]))]

    return _cached(f"ws:{site}:{prefix}", 86400, fetch)


def wikisource_text(site: str, page: str) -> str:
    resp = _get(f"https://{site}.wikisource.org/w/api.php", {"action": "parse", "prop": "wikitext", "format": "json", "page": page})
    data = resp.json()
    if "parse" not in data:
        raise HTTPException(404, {"code": "not_found", "message": "Page not found"})
    return strip_wikitext(data["parse"]["wikitext"]["*"])


def gutenberg_chapters(url: str) -> list[dict[str, str]]:
    def fetch():
        text = strip_gutenberg(_get(url).text)
        parts = re.split(r"\n\s*((?:CHAPTER|Chapter|ADVENTURE|Adventure)\s+[IVXLC\d]+\.?[^\n]*)\n", text)
        chapters = []
        for i in range(1, len(parts) - 1, 2):
            body = parts[i + 1].replace("_", "")
            if len(body.strip()) < 500:
                continue  # the table of contents and other stubs
            chapters.append({"page": str(len(chapters)), "title": " ".join(parts[i].split())[:80], "text": body})
        if not chapters:
            chapters = [{"page": "0", "title": "Celý text", "text": text}]
        return chapters

    return _cached(f"gb:{url}", 86400, fetch)


def fetch_url_text(url: str) -> str:
    if not re.match(r"^https?://", url):
        raise HTTPException(400, {"code": "bad_url", "message": "Enter a web address starting with http:// or https://"})
    m = re.match(r"^https?://([a-z\-]+)\.wikisource\.org/wiki/(.+)$", url)
    if m:
        return wikisource_text(m.group(1), requests.utils.unquote(m.group(2)).replace("_", " "))
    resp = _get(url)
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    if "html" in ctype:
        return strip_html(text)
    if "gutenberg.org" in url:
        return strip_gutenberg(text)
    return text


# ----- routes -----
@router.get("/library")
def get_library():
    voice = require_voice()
    language = load_settings(voice)["language"]
    return {"items": [{k: v for k, v in b.items() if k in ("id", "title", "author", "source")} for b in BOOKS.get(language, [])]}


@router.get("/library/{book_id}")
def get_book(book_id: str):
    voice = require_voice()
    language = load_settings(voice)["language"]
    book = next((b for b in BOOKS.get(language, []) if b["id"] == book_id), None)
    if book is None:
        raise HTTPException(404, {"code": "not_found", "message": "Unknown book"})
    try:
        if book["source"] == "wikisource":
            chapters = wikisource_chapters(book["site"], book["prefix"])
        else:
            chapters = [{"page": c["page"], "title": c["title"]} for c in gutenberg_chapters(book["url"])]
    except requests.RequestException as exc:
        raise HTTPException(502, {"code": "fetch_failed", "message": f"Could not fetch the book: {exc}"}) from exc
    return {"id": book_id, "title": book["title"], "author": book["author"], "chapters": chapters}


@router.post("/library/queue")
def queue_text(body: dict[str, Any]):
    """Queues the sentences of a chapter, a web page or pasted text at the front of the reading queue."""
    voice = require_voice()
    language = load_settings(voice)["language"]
    source = ""
    try:
        if body.get("book"):
            book = next((b for b in BOOKS.get(language, []) if b["id"] == body["book"]), None)
            if book is None:
                raise HTTPException(404, {"code": "not_found", "message": "Unknown book"})
            page = str(body.get("page", ""))
            if book["source"] == "wikisource":
                text = wikisource_text(book["site"], page)
                source = f"{book['title']} · {page.split('/')[-1]}"
            else:
                chapter = next((c for c in gutenberg_chapters(book["url"]) if c["page"] == page), None)
                if chapter is None:
                    raise HTTPException(404, {"code": "not_found", "message": "Unknown chapter"})
                text = chapter["text"]
                source = f"{book['title']} · {chapter['title']}"
        elif body.get("url"):
            text = fetch_url_text(str(body["url"]).strip())
            source = str(body["url"]).strip()[:80]
        else:
            text = str(body.get("text", ""))
    except requests.RequestException as exc:
        raise HTTPException(502, {"code": "fetch_failed", "message": f"Could not fetch the text: {exc}"}) from exc
    sentences = sentences_of(text)
    if not sentences:
        raise HTTPException(400, {"code": "no_sentences", "message": "No sentences found in the text"})
    if not source:
        source = (sentences[0][:40] + "…") if len(sentences[0]) > 40 else sentences[0]
    added = prompts.add_custom(voice, "\n".join(sentences), source=source)
    return {"added": added, "sentences": len(sentences)}
