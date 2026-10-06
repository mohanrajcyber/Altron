from __future__ import annotations

"""Desktop skills — Notepad, Explorer (WhatsApp lives in whatsapp_agent)."""

import os
import re
import tempfile
from pathlib import Path

from altron.adapters import computer


def notepad_write(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return "Say what to write, e.g. notepad write meeting notes"
    body = re.sub(
        r"^(notepad\s+write|write\s+in\s+notepad|type\s+in\s+notepad)\s*",
        "",
        body,
        flags=re.I,
    ).strip()
    if not body:
        computer.open_app("notepad")
        return "Opened Notepad — say: notepad write your text"
    fd, path = tempfile.mkstemp(prefix="altron_note_", suffix=".txt")
    os.close(fd)
    Path(path).write_text(body + "\n", encoding="utf-8")
    notepad = computer.resolve_app("notepad.exe") or "notepad.exe"
    computer.launch_process([notepad, path])
    return f"Opened Notepad with your text ({len(body)} chars)."


def notepad_open() -> str:
    return computer.open_app("notepad")


def explorer_open(path: str | None = None) -> str:
    target = (path or "").strip().strip("\"'")
    if target:
        target = re.sub(r"^(open\s+folder|open\s+explorer|explorer)\s*", "", target, flags=re.I).strip()
    if target and not Path(target).exists():
        expanded = os.path.expanduser(target)
        if Path(expanded).exists():
            target = expanded
        else:
            return f"Folder not found: {target}"
    return computer.open_explorer(target or None)


def calc_open() -> str:
    return computer.open_app("calculator")
