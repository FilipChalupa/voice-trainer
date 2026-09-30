"""Reading the output of a worker subprocess: lines end with \\n or \\r (tqdm redraws), ``@@{json}`` lines are
events, ``NN%|`` lines are progress bars."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable

PROGRESS_BAR = re.compile(r"^\s*(\d{1,3})%\|")


def pump(proc: subprocess.Popen, handle_line: Callable[[str], None]) -> None:
    """Feeds every line of the process' stdout to ``handle_line`` until it closes."""
    assert proc.stdout is not None
    buf = b""
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        while True:
            idx = min((i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0), default=-1)
            if idx < 0:
                break
            handle_line(buf[:idx].decode("utf-8", errors="replace"))
            buf = buf[idx + 1 :]
    if buf.strip():
        handle_line(buf.decode("utf-8", errors="replace"))


def parse_event(line: str) -> dict[str, Any] | None:
    """The event of an ``@@{json}`` line, or None for ordinary output."""
    if not line.startswith("@@"):
        return None
    try:
        ev = json.loads(line[2:])
    except json.JSONDecodeError:
        return None
    return ev if isinstance(ev, dict) else None


def progress_percent(line: str) -> int | None:
    m = PROGRESS_BAR.match(line)
    return int(m.group(1)) if m else None
