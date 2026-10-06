from __future__ import annotations

"""ALTRON trusted PC roots — Jarvis-safe folder allowlist.

Inspired by n8n/Activepieces credential+resource scoping:
only paths the user explicitly trusts can be listed/copied/moved.
"""

import json
from pathlib import Path

from altron.adapters.workspace import resolve_allowed

# Never allow these even if user adds a root above them incorrectly
BLOCK_NAMES = {".env", ".ssh", ".aws", "api.txt"}


def _roots_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows" / "roots.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def default_roots() -> list[str]:
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    out: list[str] = []
    for c in candidates:
        try:
            if c.is_dir():
                out.append(str(c.resolve()))
        except OSError:
            continue
    return out


def list_roots(settings) -> list[dict]:
    path = _roots_path(settings)
    if not path.exists():
        roots = default_roots()
        # Always include ALTRON workspace
        ws = str(Path(settings.altron_workspace).resolve())
        if ws not in roots:
            roots.insert(0, ws)
        save_roots(settings, roots)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("roots") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raw = []
    except (OSError, json.JSONDecodeError):
        raw = []
    items: list[dict] = []
    for r in raw:
        try:
            p = Path(str(r)).expanduser().resolve()
        except OSError:
            continue
        items.append({"path": str(p), "name": p.name or str(p), "ok": p.is_dir()})
    return items


def save_roots(settings, roots: list[str]) -> list[dict]:
    cleaned: list[str] = []
    for r in roots:
        try:
            p = Path(str(r)).expanduser().resolve()
        except OSError:
            continue
        if not p.is_dir():
            continue
        s = str(p)
        if s not in cleaned:
            cleaned.append(s)
    path = _roots_path(settings)
    path.write_text(json.dumps({"roots": cleaned}, indent=2), encoding="utf-8")
    return list_roots(settings)


def add_root(settings, root: str) -> dict:
    items = [x["path"] for x in list_roots(settings)]
    try:
        p = Path(str(root)).expanduser().resolve()
    except OSError as exc:
        return {"ok": False, "message": str(exc)}
    if not p.is_dir():
        return {"ok": False, "message": f"Not a folder: {p}"}
    if str(p) not in items:
        items.append(str(p))
    save_roots(settings, items)
    return {"ok": True, "message": f"Trusted: {p}", "roots": list_roots(settings)}


def remove_root(settings, root: str) -> dict:
    try:
        target = str(Path(str(root)).expanduser().resolve())
    except OSError:
        target = str(root)
    items = [x["path"] for x in list_roots(settings) if x["path"] != target]
    save_roots(settings, items)
    return {"ok": True, "message": f"Removed trust: {target}", "roots": list_roots(settings)}


def root_paths(settings) -> list[Path]:
    return [Path(x["path"]) for x in list_roots(settings) if x.get("ok")]


def resolve_in_roots(settings, raw: str) -> Path | None:
    roots = root_paths(settings)
    if not roots:
        return None
    path = resolve_allowed(raw, roots, base=roots[0])
    if path is None:
        return None
    # Extra deny for secrets under trusted trees
    if path.name.lower() in {n.lower() for n in BLOCK_NAMES}:
        return None
    return path


def list_dir(settings, rel_or_abs: str = "", max_n: int = 80, recursive: bool = False, pattern: str = "") -> dict:
    roots = root_paths(settings)
    if not roots:
        return {"ok": False, "message": "No trusted roots. Add folders in Flows → Roots.", "entries": [], "files": []}
    raw = (rel_or_abs or "").strip() or str(roots[0])
    path = resolve_in_roots(settings, raw)
    if path is None or not path.is_dir():
        return {"ok": False, "message": f"Blocked or missing folder: {raw}", "entries": [], "files": []}

    pat = (pattern or "").strip().lower().replace("*", "")
    entries: list[dict] = []

    def match(name: str) -> bool:
        return (not pat) or pat in name.lower()

    def add_entry(child: Path) -> None:
        if child.name.startswith(".") and child.name not in {".continue"}:
            return
        if not match(child.name):
            return
        entries.append(
            {
                "name": child.name,
                "path": str(child.resolve()),
                "type": "dir" if child.is_dir() else "file",
            }
        )

    try:
        if recursive:
            depth_limit = 3
            for child in path.rglob("*"):
                if len(entries) >= max_n:
                    break
                try:
                    rel = child.relative_to(path)
                except ValueError:
                    continue
                if len(rel.parts) > depth_limit:
                    continue
                # stay inside trusted root
                if resolve_in_roots(settings, str(child)) is None:
                    continue
                add_entry(child)
        else:
            children = sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
            for child in children:
                if len(entries) >= max_n:
                    break
                add_entry(child)
    except OSError as exc:
        return {"ok": False, "message": str(exc), "entries": [], "files": []}

    files = [e for e in entries if e["type"] == "file"]
    return {
        "ok": True,
        "folder": path.name,
        "path": str(path),
        "recursive": bool(recursive),
        "pattern": pattern or "",
        "count": len(entries),
        "file_count": len(files),
        "entries": entries,
        "files": files,
    }
