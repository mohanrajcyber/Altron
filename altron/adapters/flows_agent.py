from __future__ import annotations

"""Phase 3 — autonomous execution agent for ALTRON FLOWS.

Outer loop around run_flow:
  PLAN context → EXECUTE → OBSERVE → VERIFY → RETRY/RECOVER/STOP

Does not rewrite the Phase 1/2 engine. Checkpoints persisted under data/flows/checkpoints/.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any

from altron.adapters import flows_engine, flows_recover, flows_risk, flows_verify


def _ckpt_dir(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows" / "checkpoints"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_checkpoint(settings, flow_id: str, run: dict, extra: dict | None = None) -> str:
    cid = f"{flow_id}_{run.get('id') or uuid.uuid4().hex[:8]}"
    payload = {
        "checkpoint_id": cid,
        "flow_id": flow_id,
        "run_id": run.get("id"),
        "saved_at": time.time(),
        "status": run.get("status"),
        "ok": run.get("ok"),
        "variables": run.get("variables") or {},
        "completed_nodes": [
            r.get("nodeId") for r in (run.get("nodeResults") or []) if r.get("status") == "SUCCESS"
        ],
        "failed_nodes": [
            r.get("nodeId") for r in (run.get("nodeResults") or []) if r.get("status") == "FAILED"
        ],
        "foreach": run.get("foreach"),
        "extra": extra or {},
    }
    path = _ckpt_dir(settings) / f"{cid}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return cid


def load_checkpoint(settings, checkpoint_id: str) -> dict | None:
    path = _ckpt_dir(settings) / f"{checkpoint_id}.json"
    if not path.is_file():
        # fuzzy
        matches = list(_ckpt_dir(settings).glob(f"*{checkpoint_id}*.json"))
        if not matches:
            return None
        path = matches[0]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_checkpoints(settings, flow_id: str = "") -> list[dict]:
    out = []
    for path in sorted(_ckpt_dir(settings).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if flow_id and data.get("flow_id") != flow_id:
            continue
        out.append(
            {
                "checkpoint_id": data.get("checkpoint_id") or path.stem,
                "flow_id": data.get("flow_id"),
                "run_id": data.get("run_id"),
                "status": data.get("status"),
                "saved_at": data.get("saved_at"),
            }
        )
    return out[:40]


def _attach_meta(settings, run: dict, meta: dict) -> dict:
    """Merge Phase-3 metadata into persisted run file."""
    run_id = run.get("id")
    if not run_id:
        return run
    path = Path(settings.altron_data_dir) / "flows" / "runs" / f"{run_id}.json"
    if not path.is_file():
        run.update(meta)
        return run
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = dict(run)
    data.update(meta)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return data


def run_autonomous(
    settings,
    flow_id: str,
    *,
    max_attempts: int = 3,
    verify: bool = True,
    resume_checkpoint: str = "",
) -> dict[str, Any]:
    """Execute flow with observe → verify → bounded retry recovery.

    Returns enriched run dict (final attempt) with phase3 metadata.
    """
    flow = flows_engine.get_flow(settings, flow_id)
    if not flow:
        return {"ok": False, "status": "FAILED", "message": "Flow not found", "logs": [], "nodeResults": []}

    flows_risk.annotate_flow(flow)
    timeline: list[dict] = []
    retries: list[dict] = []
    recovery_actions: list[dict] = []
    attempt = 0
    run: dict = {}
    ckpt_id = ""
    verification: dict[str, Any] = {"ok": True, "checks": []}

    if resume_checkpoint:
        ckpt = load_checkpoint(settings, resume_checkpoint)
        timeline.append({"event": "resume", "checkpoint": resume_checkpoint, "at": time.time(), "ckpt": bool(ckpt)})
        # Resume = re-run flow (destructive nodes still go through normal safety at chat layer).
        # Variables from checkpoint are recorded for context; engine starts clean for safety.
        if ckpt:
            timeline.append(
                {
                    "event": "checkpoint_loaded",
                    "completed": ckpt.get("completed_nodes"),
                    "failed": ckpt.get("failed_nodes"),
                    "at": time.time(),
                }
            )

    while attempt < max_attempts:
        attempt += 1
        timeline.append({"event": "execute", "attempt": attempt, "at": time.time()})
        run = flows_engine.run_flow(settings, flow_id)
        timeline.append(
            {
                "event": "observe",
                "attempt": attempt,
                "status": run.get("status"),
                "ok": run.get("ok"),
                "at": time.time(),
            }
        )

        verification = {"ok": True, "checks": []}
        if verify:
            verification = flows_verify.verify_run(settings, flow, run)
            timeline.append({"event": "verify", "ok": verification.get("ok"), "at": time.time()})

        ckpt_id = save_checkpoint(settings, flow_id, run, {"attempt": attempt, "verification": verification})

        if run.get("ok") and verification.get("ok"):
            enriched = _attach_meta(
                settings,
                run,
                {
                    "phase3": {
                        "autonomous": True,
                        "attempts": attempt,
                        "retries": retries,
                        "recovery": recovery_actions,
                        "verification": verification,
                        "timeline": timeline,
                        "checkpoint_id": ckpt_id,
                        "risk": (flow.get("permissions") or {}).get("risk_level"),
                    }
                },
            )
            return enriched

        # Failure path — classify recovery
        plan = flows_recover.plan_recovery(run, attempt=len(retries))
        recovery_actions.append({**plan, "at": time.time(), "attempt": attempt})
        timeline.append({"event": "recovery", "plan": plan, "at": time.time()})

        if plan.get("action") == "retry" and attempt < max_attempts:
            retries.append(
                {
                    "nodeId": plan.get("nodeId"),
                    "attempt": plan.get("attempt"),
                    "error": plan.get("error"),
                    "at": time.time(),
                }
            )
            time.sleep(0.15)
            continue

        # stop / skip / exhausted
        break

    if not verification:
        verification = flows_verify.verify_run(settings, flow, run) if verify else {"ok": bool(run.get("ok")), "checks": []}

    enriched = _attach_meta(
        settings,
        run,
        {
            "phase3": {
                "autonomous": True,
                "attempts": attempt,
                "retries": retries,
                "recovery": recovery_actions,
                "verification": verification,
                "timeline": timeline,
                "checkpoint_id": ckpt_id,
                "risk": (flow.get("permissions") or {}).get("risk_level"),
                "final": "recovered" if run.get("ok") else "stopped",
            }
        },
    )
    return enriched


def explain_plan(plan: dict) -> str:
    """Human-readable plan explanation for chat."""
    lines = []
    name = plan.get("name") or "Untitled"
    summary = plan.get("summary") or ""
    lines.append(f"Plan: {name}")
    if summary:
        lines.append(f"Summary: {summary}")
    expl = plan.get("explanation") or plan.get("rationale") or ""
    if expl:
        lines.append(f"Why: {expl}")
    nodes = plan.get("nodes") or []
    if nodes:
        lines.append("Steps:")
        for i, n in enumerate(nodes, 1):
            lines.append(f"  {i}. {n.get('label') or n.get('type')} ({n.get('type')})")
    risk = plan.get("risk_level") or ""
    if not risk and nodes:
        fake = {"nodes": nodes, "permissions": {}}
        risk = flows_risk.classify_flow(fake).get("risk_level")
    if risk:
        lines.append(f"Risk: {risk}")
    if plan.get("requires_confirm"):
        lines.append("Confirmation: required before execute")
    missing = plan.get("missing") or []
    if missing:
        lines.append("Missing info: " + ", ".join(str(m) for m in missing))
    return "\n".join(lines)
