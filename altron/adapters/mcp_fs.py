from __future__ import annotations

from pathlib import Path

from altron.adapters.workspace import MAX_LIST, MAX_READ_BYTES, MAX_WRITE_BYTES, resolve_allowed


def fs_list(path: str, roots: list[Path], base: Path) -> str:
    target = resolve_allowed(path or ".", roots, base=base)
    if target is None:
        return "Blocked: path is outside the ALTRON workspace or is a secret file."
    if not target.exists():
        return f"Not found: {target}"
    if target.is_file():
        return f"File {target.name} ({target.stat().st_size} bytes)"
    entries: list[str] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return f"Cannot list {target}: {exc}"
    for child in children:
        if child.name.lower() in {".env", ".venv", "__pycache__"}:
            continue
        mark = "/" if child.is_dir() else ""
        entries.append(child.name + mark)
        if len(entries) >= MAX_LIST:
            break
    return f"{target}\n" + "\n".join(entries) if entries else f"{target} (empty)"


def fs_read(path: str, roots: list[Path], base: Path) -> str:
    target = resolve_allowed(path, roots, base=base)
    if target is None:
        return "Blocked: path is outside the ALTRON workspace or is a secret file."
    if not target.is_file():
        return f"Not a file: {path}"
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        return f"File too large ({size} bytes). Cap is {MAX_READ_BYTES}."
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "Binary file; not shown."
    except OSError as exc:
        return f"Cannot read: {exc}"
    return f"{target.name} ({len(text)} chars)\n{text}"


def fs_write(path: str, content: str, roots: list[Path], sandbox: Path) -> str:
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return f"Content too large. Cap is {MAX_WRITE_BYTES} bytes."
    sandbox.mkdir(parents=True, exist_ok=True)
    target = resolve_allowed(path, [sandbox], base=sandbox)
    if target is None:
        return "Blocked: writes are only allowed under data/sandbox."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {target} ({len(content)} chars)."
