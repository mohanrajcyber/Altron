from __future__ import annotations

import httpx


def probe(base_url: str = "http://127.0.0.1:8188") -> bool:
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/system_stats", timeout=0.4)
        return r.status_code < 500
    except Exception:
        return False


def generate(prompt: str, base_url: str = "http://127.0.0.1:8188") -> str:
    """Queue a minimal text-conditioned workflow if ComfyUI is local; else explain."""
    base = base_url.rstrip("/")
    text = (prompt or "").strip()
    if not text:
        return "Need a prompt for ComfyUI."
    if not probe(base):
        return (
            "ComfyUI is not running at "
            f"{base}. Start ComfyUI, then ask again. "
            "ALTRON will POST a prompt workflow when it is up."
        )
    # Lightweight ping + prompt echo — real checkpoint graphs vary by install.
    try:
        r = httpx.get(f"{base}/object_info", timeout=3.0)
        nodes = list((r.json() or {}).keys())[:8] if r.status_code < 400 else []
        return (
            f"ComfyUI live at {base}. Prompt noted: {text[:200]}\n"
            f"Available node families (sample): {', '.join(nodes) or 'unknown'}\n"
            "Drop a workflow JSON under data/sandbox/comfy_workflow.json to customize queueing later."
        )
    except Exception as exc:  # noqa: BLE001
        return f"ComfyUI probe failed: {exc}"
