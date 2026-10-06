from __future__ import annotations

"""ALTRON IDE file history — undo/revert after AGI or editor writes."""

import json
import time
from pathlib import Path

MAX_ENTRIES = 40


def _store(settings) -> Path:
    p = Path(settings.altron_data_dir) / "ide" / "history.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load(settings) -> list[dict]:
    path = _store(settings)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save(settings, items: list[dict]) -> None:
    _store(settings).write_text(json.dumps(items[-MAX_ENTRIES:], indent=2), encoding="utf-8")


def snapshot(settings, rel: str, before: str, after: str, source: str = "edit") -> None:
    items = _load(settings)
    items.append(
        {
            "id": f"{int(time.time() * 1000)}-{len(items)}",
            "path": rel.replace("\\", "/"),
            "before": before,
            "after": after,
            "source": source,
            "ts": time.time(),
        }
    )
    _save(settings, items)


def list_history(settings, limit: int = 20) -> list[dict]:
    items = _load(settings)
    out = []
    for it in reversed(items[-limit:]):
        out.append(
            {
                "id": it.get("id"),
                "path": it.get("path"),
                "source": it.get("source"),
                "ts": it.get("ts"),
                "before_len": len(it.get("before") or ""),
                "after_len": len(it.get("after") or ""),
            }
        )
    return out


def revert(settings, entry_id: str = "", path: str = "") -> str:
    from altron.adapters import ide_agent

    items = _load(settings)
    target = None
    if entry_id:
        for it in reversed(items):
            if it.get("id") == entry_id:
                target = it
                break
    elif path:
        want = path.replace("\\", "/")
        for it in reversed(items):
            if it.get("path") == want:
                target = it
                break
    else:
        target = items[-1] if items else None
    if not target:
        return "No history entry found."
    before = target.get("before")
    if before is None:
        return "History entry has no before snapshot."
    msg = ide_agent.write_workspace(settings, target["path"], before, record_history=False)
    if msg.lower().startswith("wrote"):
        return f"Reverted {target['path']} to previous snapshot ({target.get('id')})."
    return msg
