from __future__ import annotations

import httpx

from altron.adapters import jobs as local_jobs


def enqueue(path, title: str, payload: str = "", webhook_url: str = "") -> str:
    message = local_jobs.enqueue(path, title, payload)
    url = (webhook_url or "").strip()
    if not url:
        return message + " (local queue only — set N8N_WEBHOOK_URL for live n8n)"
    try:
        response = httpx.post(
            url,
            json={"title": title, "payload": payload, "source": "altron"},
            timeout=8.0,
        )
        if response.status_code >= 400:
            return f"{message}\nn8n webhook HTTP {response.status_code}"
        return f"{message}\nn8n webhook OK ({response.status_code})"
    except Exception as exc:  # noqa: BLE001
        return f"{message}\nn8n webhook failed: {exc}"


def probe(webhook_url: str = "", base_url: str = "http://127.0.0.1:5678") -> dict:
    url = (webhook_url or "").strip()
    base = (base_url or "").rstrip("/")
    ok = False
    try:
        r = httpx.get(f"{base}/healthz", timeout=0.4)
        ok = r.status_code < 500
    except Exception:
        ok = False
    return {"ok": ok, "webhook": bool(url), "base": base}
