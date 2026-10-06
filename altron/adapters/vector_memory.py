from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

DIM = 128
COLLECTION = "altron"


def _embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    tokens = [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if t]
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for i in range(0, 16, 4):
            idx = int.from_bytes(digest[i : i + 2], "little") % DIM
            sign = 1.0 if digest[i + 2] % 2 == 0 else -1.0
            vec[idx] += sign
        for i in range(len(token) - 1):
            bigram = token[i : i + 2]
            h = hashlib.md5(bigram.encode("utf-8")).digest()
            idx = int.from_bytes(h[:2], "little") % DIM
            vec[idx] += 0.5
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class VectorMemory:
    """Mem0-shaped add/search. Prefers Qdrant when reachable; always mirrors locally."""

    def __init__(self, path: Path, qdrant_url: str = "") -> None:
        self.path = path
        self.qdrant_url = (qdrant_url or "").rstrip("/")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self._qdrant_ready: bool | None = None

    def add(self, text: str, kind: str = "note") -> dict:
        text = text.strip()
        if not text:
            return {}
        record = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "text": text,
            "vec": _embed(text),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._qdrant_upsert(record)
        return record

    def search(self, query: str, limit: int = 8) -> list[str]:
        q = query.strip()
        rows = self._load()
        if not q:
            return [r["text"] for r in rows[-limit:]]
        remote = self._qdrant_search(q, limit=limit)
        if remote:
            return remote
        qv = _embed(q)
        scored = [(_cosine(qv, r.get("vec") or _embed(r.get("text", ""))), r.get("text", "")) for r in rows]
        scored = [(s, t) for s, t in scored if t]
        scored.sort(key=lambda item: item[0], reverse=True)
        hits = [t for s, t in scored[:limit] if s > 0.05]
        return hits or [r["text"] for r in rows[-limit:]]

    def backend(self) -> str:
        return "qdrant" if self._qdrant_ok() else "local_vector"

    def sync_all_to_qdrant(self) -> int:
        if not self._ensure_collection():
            return 0
        n = 0
        for row in self._load():
            if row.get("text") and row.get("vec"):
                self._qdrant_upsert(row)
                n += 1
        return n

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

    def _qdrant_ok(self) -> bool:
        if self._qdrant_ready is not None:
            return self._qdrant_ready
        if not self.qdrant_url:
            self._qdrant_ready = False
            return False
        try:
            import httpx

            r = httpx.get(f"{self.qdrant_url}/collections", timeout=0.5)
            self._qdrant_ready = r.status_code < 500
        except Exception:
            self._qdrant_ready = False
        return self._qdrant_ready

    def _ensure_collection(self) -> bool:
        if not self._qdrant_ok():
            return False
        try:
            import httpx

            base = self.qdrant_url
            r = httpx.get(f"{base}/collections/{COLLECTION}", timeout=1.0)
            if r.status_code == 200:
                return True
            put = httpx.put(
                f"{base}/collections/{COLLECTION}",
                json={"vectors": {"size": DIM, "distance": "Cosine"}},
                timeout=3.0,
            )
            return put.status_code < 300
        except Exception:
            return False

    def _qdrant_upsert(self, record: dict) -> None:
        if not self._ensure_collection():
            return
        try:
            import httpx

            httpx.put(
                f"{self.qdrant_url}/collections/{COLLECTION}/points?wait=true",
                json={
                    "points": [
                        {
                            "id": int(record["id"][:8], 16) % (2**31 - 1),
                            "vector": record["vec"],
                            "payload": {"text": record["text"], "kind": record.get("kind") or "note"},
                        }
                    ]
                },
                timeout=2.0,
            )
        except Exception:
            return

    def _qdrant_search(self, query: str, limit: int = 8) -> list[str]:
        if not self._ensure_collection():
            return []
        try:
            import httpx

            r = httpx.post(
                f"{self.qdrant_url}/collections/{COLLECTION}/points/search",
                json={"vector": _embed(query), "limit": limit, "with_payload": True},
                timeout=2.0,
            )
            if r.status_code >= 400:
                return []
            out = []
            for hit in r.json().get("result") or []:
                text = (hit.get("payload") or {}).get("text")
                if text:
                    out.append(text)
            return out
        except Exception:
            return []
