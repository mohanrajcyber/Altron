from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def enqueue(path: Path, title: str, payload: str = "") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": uuid.uuid4().hex[:10],
        "ts": datetime.now(timezone.utc).isoformat(),
        "title": (title or "job").strip()[:200],
        "payload": (payload or "").strip()[:4000],
        "status": "queued",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return f"Queued job {record['id']}: {record['title']}"


def recent(path: Path, limit: int = 12) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(rows[-limit:]))


def format_recent(path: Path, limit: int = 12) -> str:
    items = recent(path, limit=limit)
    if not items:
        return "Job queue is empty."
    lines = [f"{it.get('id')} [{it.get('status')}] {it.get('title')}" for it in items]
    return "Jobs\n" + "\n".join(lines)
