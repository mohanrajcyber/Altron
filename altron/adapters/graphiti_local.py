from __future__ import annotations

import json
from pathlib import Path


class KnowledgeGraph:
    """Graphiti-shaped entity/relation store (local JSON)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save({"nodes": [], "edges": []})

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"nodes": [], "edges": []}

    def save(self, data: dict) -> None:
        clean = {
            "nodes": list(data.get("nodes") or [])[:200],
            "edges": list(data.get("edges") or [])[:400],
        }
        self.path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, subject: str, relation: str, obj: str) -> str:
        s, r, o = subject.strip(), relation.strip(), obj.strip()
        if not (s and r and o):
            return "Need subject, relation, and object."
        data = self.load()
        for name in (s, o):
            if name not in data["nodes"]:
                data["nodes"].append(name)
        edge = {"s": s, "r": r, "o": o}
        if edge not in data["edges"]:
            data["edges"].append(edge)
        self.save(data)
        return f"Graph: {s} -{r}-> {o}"

    def search(self, query: str, limit: int = 12) -> str:
        q = (query or "").lower().strip()
        data = self.load()
        edges = data.get("edges") or []
        if not edges:
            return "Knowledge graph is empty."
        if not q:
            picks = edges[-limit:]
        else:
            picks = [e for e in edges if q in f"{e.get('s')} {e.get('r')} {e.get('o')}".lower()][:limit]
            if not picks:
                picks = edges[-limit:]
        lines = [f"{e['s']} -{e['r']}-> {e['o']}" for e in picks]
        return "Graph\n" + "\n".join(lines)
