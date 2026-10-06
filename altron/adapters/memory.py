from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone


class JsonlMemory:
    """Letta-style archival block stored as JSONL. Mem0/Qdrant replace this later."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def write(self, text: str, kind: str = "note") -> dict:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "text": text.strip(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def search(self, query: str, limit: int = 8) -> list[str]:
        rows = self._load()
        q = query.lower().strip()
        if not q:
            return [r["text"] for r in rows[-limit:]]
        scored: list[tuple[int, str]] = []
        for row in rows:
            text = row.get("text", "")
            score = sum(1 for token in q.split() if token in text.lower())
            if score:
                scored.append((score, text))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            return [text for _, text in scored[:limit]]
        return [r["text"] for r in rows[-limit:]]

    def recent(self, limit: int = 24) -> list[dict]:
        rows = self._load()
        return list(reversed(rows[-limit:]))

    def _load(self) -> list[dict]:
        rows: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
