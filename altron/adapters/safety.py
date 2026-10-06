from __future__ import annotations

"""Confirm gate for risky actions — world-class AGI does not freestyle deletes/sends."""

import json
import time
from pathlib import Path

TTL_SEC = 120


def request(path: Path, kind: str, payload: dict, hint: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = kind.upper().replace(" ", "_")
    data = {
        "kind": kind,
        "payload": payload,
        "hint": hint,
        "token": token,
        "ts": time.time(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return (
        f"Safety hold: {hint}\n"
        f"Type CONFIRM {token} within {TTL_SEC}s to proceed. Or say CANCEL."
    )


def pending(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if time.time() - float(data.get("ts") or 0) > TTL_SEC:
        clear(path)
        return None
    return data


def clear(path: Path) -> None:
    if path.exists():
        path.unlink()


def matches_confirm(text: str, path: Path) -> dict | None:
    data = pending(path)
    if not data:
        return None
    lowered = (text or "").strip().upper()
    token = str(data.get("token") or "")
    if lowered in {f"CONFIRM {token}", f"CONFIRM_{token}", token}:
        return data
    if lowered.startswith("CONFIRM ") and token in lowered.replace(" ", "_"):
        return data
    return None


def is_cancel(text: str) -> bool:
    lowered = (text or "").lower().strip().rstrip(".!")
    return lowered in {"cancel", "cancel that", "never mind", "nevermind", "abort"}
