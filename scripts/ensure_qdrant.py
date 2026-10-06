from __future__ import annotations

import json

import httpx


def ensure_collection(url: str = "http://127.0.0.1:6333", name: str = "altron", dim: int = 128) -> int:
    base = url.rstrip("/")
    try:
        r = httpx.get(f"{base}/collections/{name}", timeout=2.0)
        if r.status_code == 200:
            print(f"Qdrant collection `{name}` exists")
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Qdrant not reachable at {base}: {exc}")
        print("Start Qdrant (docker run -p 6333:6333 qdrant/qdrant) — ALTRON still uses local vectors.")
        return 1
    payload = {
        "vectors": {"size": dim, "distance": "Cosine"},
    }
    r = httpx.put(f"{base}/collections/{name}", json=payload, timeout=5.0)
    print(r.status_code, r.text[:200])
    return 0 if r.status_code < 300 else 1


if __name__ == "__main__":
    raise SystemExit(ensure_collection())
