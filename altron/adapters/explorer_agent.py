from __future__ import annotations

"""File Explorer sticky — list folder → select N → open / delete (confirm)."""

import json
import os
import re
import shutil
from pathlib import Path

from altron.adapters import computer, safety

_WORD_NUM = {
    "one": 1,
    "first": 1,
    "1st": 1,
    "two": 2,
    "second": 2,
    "2nd": 2,
    "three": 3,
    "third": 3,
    "3rd": 3,
    "four": 4,
    "fourth": 4,
    "4th": 4,
    "five": 5,
    "fifth": 5,
    "5th": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def open_explorer(intent_path: Path, folder: str = "") -> str:
    root = _resolve_folder(folder) or Path.home() / "Downloads"
    if not root.exists():
        root = Path.home()
    computer.open_explorer(str(root))
    entries = _list_entries(root)
    _set_intent(intent_path, "explorer_control", folder=str(root), selected=0, entries=entries)
    preview = "\n".join(f"{i+1}. {n}" for i, n in enumerate(entries[:15]))
    return (
        f"Explorer under ALTRON control: {root}\n"
        f"{preview or '(empty)'}\n"
        "Say: select 1 / select number one · open · delete · list · open folder Documents · close explorer"
    )


def act(user_text: str, intent_path: Path, settings) -> str:
    text = (user_text or "").strip()
    if not text:
        return "Explorer listening — select N · open · delete · list · close explorer"
    lowered = text.lower().strip().rstrip(".!?")
    data = _read_intent(intent_path)

    if _wants_close(lowered):
        return close_explorer(intent_path)

    if re.search(r"\b(open folder|go to folder|cd|open explorer)\b", lowered) or lowered.startswith("folder "):
        folder = re.sub(
            r"^(open folder|go to folder|cd|open explorer|folder)\s*",
            "",
            text,
            flags=re.I,
        ).strip().strip("\"'")
        return open_explorer(intent_path, folder)

    if lowered in {"list", "list files", "show files", "refresh", "ls", "dir"}:
        return _refresh_list(intent_path)

    idx = _select_index(lowered)
    if idx:
        return select_index(intent_path, idx)

    if lowered in {"open", "open it", "open file", "open selected", "launch"}:
        return open_selected(intent_path)

    if lowered in {"delete", "delete it", "remove", "remove file", "delete selected"}:
        return request_delete(intent_path, settings)

    # select by partial name
    m = re.match(r"^(select|open)\s+(.+)$", text, flags=re.I)
    if m:
        name = m.group(2).strip().strip("\"'")
        if _select_index(name.lower()):
            return select_index(intent_path, _select_index(name.lower()) or 1)
        return select_by_name(intent_path, name)

    return (
        "Explorer is listening. Try: select 1 · open · delete · list · "
        "open folder Downloads · close explorer"
    )


def select_index(intent_path: Path, index: int) -> str:
    data = _read_intent(intent_path)
    folder = Path(data.get("folder") or (Path.home() / "Downloads"))
    entries = data.get("entries") or _list_entries(folder)
    idx = max(1, min(int(index), len(entries) or 1))
    if not entries or idx > len(entries):
        return f"Only {len(entries)} items — pick a smaller number."
    name = entries[idx - 1]
    _set_intent(intent_path, "explorer_control", folder=str(folder), selected=idx, entries=entries)
    return f"Selected #{idx}: {name}\nSay open · delete · select another · close explorer"


def select_by_name(intent_path: Path, name: str) -> str:
    data = _read_intent(intent_path)
    folder = Path(data.get("folder") or (Path.home() / "Downloads"))
    entries = data.get("entries") or _list_entries(folder)
    needle = name.lower()
    for i, n in enumerate(entries, start=1):
        if needle in n.lower():
            return select_index(intent_path, i)
    return f"No match for '{name}' in {folder}. Say list."


def open_selected(intent_path: Path) -> str:
    path = _selected_path(intent_path)
    if not path:
        return "Select a file first: select 1"
    try:
        computer.start_file(str(path))
        return f"Opened: {path.name}"
    except Exception as exc:  # noqa: BLE001
        return f"Open failed: {exc}"


def request_delete(intent_path: Path, settings) -> str:
    path = _selected_path(intent_path)
    if not path:
        return "Select a file first: select 1"
    return safety.request(
        settings.safety_path,
        "fs_delete",
        {"path": str(path)},
        f"Permanently delete {path}",
    )


def execute_delete(path_str: str) -> str:
    path = Path(path_str)
    # Safety: only under user profile (home) — never system roots
    home = Path.home().resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        return f"Bad path: {exc}"
    if home not in resolved.parents and resolved != home:
        # allow Desktop/Downloads/Documents under home only
        return f"Blocked delete outside your user folder: {resolved}"
    if not resolved.exists():
        return f"Already gone: {resolved}"
    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return f"Deleted: {resolved}"
    except OSError as exc:
        return f"Delete failed: {exc}"


def close_explorer(intent_path: Path) -> str:
    clear_expect(intent_path)
    return "Closed Explorer control."


def expecting_control(intent_path: Path) -> bool:
    return _read_intent(intent_path).get("expect") == "explorer_control"


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def _refresh_list(intent_path: Path) -> str:
    data = _read_intent(intent_path)
    folder = Path(data.get("folder") or (Path.home() / "Downloads"))
    entries = _list_entries(folder)
    _set_intent(
        intent_path,
        "explorer_control",
        folder=str(folder),
        selected=int(data.get("selected") or 0),
        entries=entries,
    )
    preview = "\n".join(f"{i+1}. {n}" for i, n in enumerate(entries[:20]))
    return f"{folder}\n{preview or '(empty)'}"


def _selected_path(intent_path: Path) -> Path | None:
    data = _read_intent(intent_path)
    folder = Path(data.get("folder") or "")
    entries = data.get("entries") or []
    sel = int(data.get("selected") or 0)
    if not folder.exists() or sel < 1 or sel > len(entries):
        return None
    return folder / entries[sel - 1]


def _list_entries(folder: Path) -> list[str]:
    try:
        kids = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []
    out: list[str] = []
    for child in kids:
        if child.name.startswith("."):
            continue
        out.append(child.name + ("/" if child.is_dir() else ""))
        if len(out) >= 40:
            break
    return out


def _resolve_folder(raw: str) -> Path | None:
    text = (raw or "").strip().strip("\"'")
    if not text:
        return None
    shortcuts = {
        "downloads": Path.home() / "Downloads",
        "download": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
        "docs": Path.home() / "Documents",
        "desktop": Path.home() / "Desktop",
        "home": Path.home(),
        "pictures": Path.home() / "Pictures",
        "music": Path.home() / "Music",
        "videos": Path.home() / "Videos",
    }
    key = text.lower().rstrip("/\\")
    if key in shortcuts:
        return shortcuts[key]
    p = Path(os.path.expanduser(text))
    if p.exists():
        return p
    return None


def _select_index(lowered: str) -> int | None:
    if re.search(r"\b(select|choose|pick)\b", lowered) or re.match(
        r"^(number|file|item|folder)\b", lowered
    ):
        m = re.search(r"\b(\d+)\b", lowered)
        if m:
            return int(m.group(1))
        for w, n in _WORD_NUM.items():
            if re.search(rf"\b{w}\b", lowered):
                return n
    if re.match(r"^#?\d+$", lowered):
        return int(re.sub(r"\D", "", lowered))
    return None


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit)\b.+\b(explorer|folder)\b", lowered)
        or lowered in {"close explorer", "exit explorer", "stop explorer"}
    )


def _set_intent(
    path: Path,
    expect: str,
    folder: str = "",
    selected: int = 0,
    entries: list | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"expect": expect}
    if folder:
        data["folder"] = folder
    if selected:
        data["selected"] = selected
    if entries is not None:
        data["entries"] = entries
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
