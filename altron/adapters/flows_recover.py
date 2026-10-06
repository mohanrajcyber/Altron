from __future__ import annotations

"""Phase 3 — failure classification and bounded recovery for ALTRON FLOWS."""

import re
from typing import Any

MAX_RETRIES = 2

# Error patterns → recovery strategy
_RETRYABLE = [
    r"timed?\s*out",
    r"temporarily",
    r"connection",
    r"busy",
    r"locked",
    r"AI JSON schema validation failed",
    r"empty response",
]
_SKIPPABLE = [
    r"no extractable text",
    r"Password-protected PDF",
    r"Malformed PDF",
    r"Blocked or missing file",
]
_UNRECOVERABLE = [
    r"NOT IMPLEMENTED",
    r"not in trusted roots",
    r"Blocked or missing",
    r"Destructive",
    r"Denied",
]


def classify_error(error: str) -> dict[str, Any]:
    err = str(error or "")
    for pat in _UNRECOVERABLE:
        if re.search(pat, err, re.I):
            return {"class": "unrecoverable", "action": "stop", "reason": pat}
    for pat in _SKIPPABLE:
        if re.search(pat, err, re.I):
            return {"class": "skippable", "action": "skip", "reason": pat}
    for pat in _RETRYABLE:
        if re.search(pat, err, re.I):
            return {"class": "retryable", "action": "retry", "reason": pat}
    # default: retry once for transient AI/IO noise
    if err:
        return {"class": "unknown", "action": "retry", "reason": "unknown_error"}
    return {"class": "none", "action": "none", "reason": ""}


def failed_nodes(run: dict) -> list[dict]:
    out = []
    for r in run.get("nodeResults") or []:
        if r.get("status") == "FAILED":
            out.append(r)
    return out


def plan_recovery(run: dict, attempt: int = 0) -> dict[str, Any]:
    """Decide recovery for a failed run. Bounded — never infinite."""
    failed = failed_nodes(run)
    if not failed:
        return {"action": "none", "message": "No failed nodes"}
    primary = failed[-1]  # last failure
    err = str(primary.get("error") or primary.get("message") or "")
    cls = classify_error(err)
    if cls["action"] == "stop":
        return {
            "action": "stop",
            "class": cls["class"],
            "nodeId": primary.get("nodeId"),
            "error": err,
            "message": f"Unrecoverable failure on {primary.get('label')}: {err}",
        }
    if cls["action"] == "skip":
        return {
            "action": "skip",
            "class": cls["class"],
            "nodeId": primary.get("nodeId"),
            "error": err,
            "message": f"Skip recoverable item failure on {primary.get('label')}: {err}",
        }
    if cls["action"] == "retry" and attempt < MAX_RETRIES:
        return {
            "action": "retry",
            "class": cls["class"],
            "nodeId": primary.get("nodeId"),
            "attempt": attempt + 1,
            "max": MAX_RETRIES,
            "error": err,
            "message": f"Retry {attempt + 1}/{MAX_RETRIES} for {primary.get('label')}",
        }
    return {
        "action": "stop",
        "class": "exhausted",
        "nodeId": primary.get("nodeId"),
        "error": err,
        "message": f"Retries exhausted for {primary.get('label')}: {err}",
    }
