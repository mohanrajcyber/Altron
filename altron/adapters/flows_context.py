from __future__ import annotations

"""Phase 3 — structured, inspectable workflow context (not permanent free-form memory)."""

import json
import time
from pathlib import Path
from typing import Any

from altron.adapters import flows_engine


def _ctx_dir(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows" / "context"
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_context(
    settings,
    *,
    user_command: str = "",
    flow: dict | None = None,
    run: dict | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Build an inspectable context snapshot for planner/agent."""
    flow = flow or {}
    run = run or {}
    prev_runs = []
    fid = flow.get("id")
    if fid:
        for r in flows_engine.recent_runs(settings, limit=5):
            if r.get("flow_id") == fid or r.get("flowId") == fid:
                prev_runs.append(
                    {
                        "id": r.get("id"),
                        "status": r.get("status"),
                        "ok": r.get("ok"),
                        "duration_ms": r.get("duration_ms"),
                    }
                )
    variables = dict(flow.get("variables") or {})
    if run.get("variables"):
        variables.update(run.get("variables") or {})

    outputs = {}
    for nr in run.get("nodeResults") or []:
        if nr.get("status") == "SUCCESS" and nr.get("nodeId"):
            outputs[nr["nodeId"]] = {
                "label": nr.get("label"),
                "output": nr.get("output"),
            }

    ctx = {
        "version": 3,
        "at": time.time(),
        "user_command": (user_command or "")[:2000],
        "flow": {
            "id": flow.get("id"),
            "name": flow.get("name"),
            "node_types": [n.get("type") for n in (flow.get("nodes") or [])],
            "variables": variables,
            "permissions": flow.get("permissions") or {},
        },
        "execution": {
            "run_id": run.get("id"),
            "status": run.get("status"),
            "ok": run.get("ok"),
            "completed": [
                r.get("nodeId") for r in (run.get("nodeResults") or []) if r.get("status") == "SUCCESS"
            ],
            "failed": [
                r.get("nodeId") for r in (run.get("nodeResults") or []) if r.get("status") == "FAILED"
            ],
            "outputs": outputs,
            "foreach": run.get("foreach"),
            "phase3": run.get("phase3"),
        },
        "previous_runs": prev_runs,
        "extra": extra or {},
    }
    return ctx


def persist_context(settings, flow_id: str, ctx: dict) -> str:
    path = _ctx_dir(settings) / f"{flow_id}_latest.json"
    path.write_text(json.dumps(ctx, indent=2, default=str), encoding="utf-8")
    return str(path)


def load_context(settings, flow_id: str) -> dict | None:
    path = _ctx_dir(settings) / f"{flow_id}_latest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
