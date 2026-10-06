from __future__ import annotations

import time

import httpx

from altron.settings import Settings

_CACHE: dict = {"t": 0.0, "v": None}


def ollama_base(settings: Settings) -> str:
    return (settings.ollama_base_url or "http://127.0.0.1:11434/v1").rstrip("/")


def tags_url(settings: Settings) -> str:
    base = ollama_base(settings)
    root = base[:-3] if base.endswith("/v1") else base
    return root.rstrip("/") + "/api/tags"


def probe(settings: Settings, timeout: float = 0.4) -> dict:
    now = time.monotonic()
    cached = _CACHE.get("v")
    if cached is not None and now - float(_CACHE.get("t") or 0) < 8:
        return cached
    try:
        response = httpx.get(tags_url(settings), timeout=timeout)
        if response.status_code >= 400:
            value = {"ok": False, "models": []}
        else:
            names = [m.get("name") for m in (response.json().get("models") or []) if m.get("name")]
            value = {"ok": True, "models": names[:12]}
    except Exception:
        value = {"ok": False, "models": []}
    _CACHE["t"] = now
    _CACHE["v"] = value
    return value


def pick_model(settings: Settings, available: list[str] | None = None) -> str:
    wanted = (settings.ollama_model or "llama3.1").strip()
    if not available:
        return wanted
    if any(name == wanted or name.startswith(wanted + ":") for name in available):
        return wanted
    return available[0]
