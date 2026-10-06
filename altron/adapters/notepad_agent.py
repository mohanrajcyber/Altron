from __future__ import annotations

"""Notepad sticky — speak = append text · save as …"""

import json
import re
from pathlib import Path

from altron.adapters import computer

DRAFT_NAME = "altron_notepad_draft.txt"


def open_notepad(intent_path: Path, data_dir: Path) -> str:
    draft = _draft_path(data_dir)
    draft.parent.mkdir(parents=True, exist_ok=True)
    if not draft.exists():
        draft.write_text("", encoding="utf-8")
    notepad = computer.resolve_app("notepad.exe") or "notepad.exe"
    computer.launch_process([notepad, str(draft)])
    _set_intent(intent_path, "notepad_control", draft=str(draft))
    return (
        "Notepad under ALTRON control.\n"
        "Speak/type anything → adds to the note.\n"
        "Say: save as shopping list · clear note · close notepad"
    )


def act(user_text: str, intent_path: Path, data_dir: Path) -> str:
    text = (user_text or "").strip()
    if not text:
        return "Notepad listening — speak to type · save as … · close notepad"
    lowered = text.lower().strip().rstrip(".!?")

    if _wants_close(lowered):
        return close_notepad(intent_path)
    if lowered in {"clear", "clear note", "clear notepad", "new note"}:
        return clear_note(intent_path, data_dir)
    if re.match(r"^save(\s+as)?\b", lowered):
        name = re.sub(r"^save(\s+as)?\s*", "", text, flags=re.I).strip().strip("\"'")
        return save_as(intent_path, data_dir, name)

    return append_text(intent_path, data_dir, text)


def append_text(intent_path: Path, data_dir: Path, body: str) -> str:
    draft = _ensure_draft(intent_path, data_dir)
    prev = draft.read_text(encoding="utf-8") if draft.exists() else ""
    sep = "" if not prev or prev.endswith("\n") else "\n"
    draft.write_text(prev + sep + body.rstrip() + "\n", encoding="utf-8")
    _set_intent(intent_path, "notepad_control", draft=str(draft))
    # Re-open so user sees update (Notepad does not always live-reload)
    notepad = computer.resolve_app("notepad.exe") or "notepad.exe"
    try:
        computer.launch_process([notepad, str(draft)])
    except Exception:
        pass
    return f"Added to note ({len(body)} chars). Say more, or: save as my notes"


def save_as(intent_path: Path, data_dir: Path, name: str) -> str:
    draft = _ensure_draft(intent_path, data_dir)
    body = draft.read_text(encoding="utf-8") if draft.exists() else ""
    if not body.strip():
        return "Note is empty — speak something first."
    safe = re.sub(r"[^\w\s\-\.]+", "", name or "note", flags=re.UNICODE).strip() or "note"
    if not safe.lower().endswith(".txt"):
        safe += ".txt"
    out_dir = Path.home() / "Documents" / "ALTRON"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / safe
    target.write_text(body, encoding="utf-8")
    notepad = computer.resolve_app("notepad.exe") or "notepad.exe"
    computer.launch_process([notepad, str(target)])
    _set_intent(intent_path, "notepad_control", draft=str(draft))
    return f"Saved: {target}"


def clear_note(intent_path: Path, data_dir: Path) -> str:
    draft = _ensure_draft(intent_path, data_dir)
    draft.write_text("", encoding="utf-8")
    _set_intent(intent_path, "notepad_control", draft=str(draft))
    return "Cleared note. Speak to start fresh."


def close_notepad(intent_path: Path) -> str:
    clear_expect(intent_path)
    return "Closed Notepad control."


def expecting_control(intent_path: Path) -> bool:
    return _read_intent(intent_path).get("expect") == "notepad_control"


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _draft_path(data_dir: Path) -> Path:
    return Path(data_dir) / "sandbox" / DRAFT_NAME


def _ensure_draft(intent_path: Path, data_dir: Path) -> Path:
    data = _read_intent(intent_path)
    raw = data.get("draft") or ""
    if raw and Path(raw).exists():
        return Path(raw)
    draft = _draft_path(data_dir)
    draft.parent.mkdir(parents=True, exist_ok=True)
    if not draft.exists():
        draft.write_text("", encoding="utf-8")
    return draft


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\bnotepad\b", lowered)
        or lowered in {"close notepad", "exit notepad", "stop notepad"}
    )


def _set_intent(path: Path, expect: str, draft: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"expect": expect}
    if draft:
        data["draft"] = draft
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
