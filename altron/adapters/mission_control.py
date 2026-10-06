from __future__ import annotations

"""ALTRON Mission Control — live observability aggregation over existing engines.

Does not execute tools itself. Surfaces flows, traces, jobs, safety, and health.
"""

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from altron import __version__
from altron.adapters import flows_engine, jobs, safety, traces
from altron.identity import IDENTITY_NAME
from altron.settings import get_settings


def _system_health() -> dict[str, Any]:
    """Best-effort host metrics. Never invent percentages when unavailable."""
    out: dict[str, Any] = {
        "cpu_percent": None,
        "ram_percent": None,
        "disk_percent": None,
        "network_online": True,
        "source": "partial",
        "all_normal": True,
    }
    try:
        import psutil  # type: ignore

        out["cpu_percent"] = round(float(psutil.cpu_percent(interval=0.05)), 1)
        out["ram_percent"] = round(float(psutil.virtual_memory().percent), 1)
        root = Path.home().anchor or "/"
        out["disk_percent"] = round(float(psutil.disk_usage(root).percent), 1)
        out["source"] = "psutil"
    except Exception:
        try:
            usage = shutil.disk_usage(Path.home())
            out["disk_percent"] = round(100.0 * usage.used / max(usage.total, 1), 1)
            out["source"] = "stdlib_disk"
        except Exception:
            out["source"] = "unavailable"
            out["all_normal"] = True
    # Soft health flags
    for key in ("cpu_percent", "ram_percent", "disk_percent"):
        val = out.get(key)
        if isinstance(val, (int, float)) and val >= 92:
            out["all_normal"] = False
    return out


def _greeting(now: datetime | None = None) -> str:
    now = now or datetime.now()
    h = now.hour
    if h < 12:
        return "Good Morning"
    if h < 17:
        return "Good Afternoon"
    return "Good Evening"


def _tools_in_use(settings, active_runs: list[dict], pending: dict | None, recent_traces: list[dict]) -> list[dict]:
    tools: dict[str, dict] = {}

    def mark(name: str, active: bool = True, detail: str = "") -> None:
        cur = tools.get(name) or {"name": name, "active": False, "detail": ""}
        cur["active"] = cur["active"] or active
        if detail:
            cur["detail"] = detail
        tools[name] = cur

    if active_runs:
        mark("File System", True, "Flow filesystem nodes")
        for run in active_runs:
            types = run.get("node_types") or []
            if any(str(t).startswith("ai.") for t in types):
                mark("AI", True, "Flow AI node")
            if any(str(t).startswith("browser.") for t in types):
                mark("Browser", True, "Browser node")
    if pending:
        kind = str(pending.get("kind") or "")
        if kind.startswith("fs_") or kind == "flow_run":
            mark("File System", True, "Awaiting approval")
        if kind == "shutdown":
            mark("Desktop", True, "Shutdown pending")
    # Recent chat tool hints from traces
    for row in (recent_traces or [])[:6]:
        for step in row.get("trace") or []:
            s = str(step).lower()
            if "browser" in s or "youtube" in s:
                mark("Browser", True, "Recent chat tool")
            if "python" in s or "ide" in s or "code_" in s:
                mark("Python", True, "Recent code/IDE")
            if "files." in s or "fs_" in s or "explorer" in s:
                mark("File System", True, "Recent file tool")
            if "ai." in s or "think" in s:
                mark("AI", True, "Recent AI")
    # Always list catalog of known surfaces as idle when nothing active
    for name in ("File System", "AI", "Python", "Browser"):
        tools.setdefault(name, {"name": name, "active": False, "detail": "Idle"})
    return list(tools.values())


def _workflow_counts(settings, active: list[dict], runs: list[dict]) -> dict[str, Any]:
    running = len(active)
    failed = sum(1 for r in runs[:20] if r.get("status") == "FAILED" or r.get("ok") is False)
    waiting = 1 if safety.pending(settings.safety_path) else 0
    # queued jobs
    try:
        for j in jobs.recent(settings.jobs_path, limit=20):
            if str(j.get("status") or "") in {"queued", "waiting"}:
                waiting += 1
    except Exception:
        pass
    return {
        "running": running,
        "waiting": waiting,
        "failed": failed,
        "items": [
            {
                "id": a.get("run_id") or a.get("id"),
                "name": a.get("flow_name") or a.get("name") or "Flow",
                "status": "RUNNING",
                "progress": a.get("progress"),
                "flow_id": a.get("flow_id"),
            }
            for a in active
        ]
        + [
            {
                "id": r.get("id"),
                "name": r.get("flow_name") or "Flow",
                "status": r.get("status") or "UNKNOWN",
                "progress": 100 if r.get("ok") else None,
                "flow_id": r.get("flow_id"),
            }
            for r in runs[:8]
            if r.get("id") not in {a.get("run_id") for a in active}
        ],
    }


def _current_mission(settings, active: list[dict], pending: dict | None, runs: list[dict]) -> dict[str, Any]:
    if pending:
        return {
            "status": "NEEDS_APPROVAL",
            "title": "Awaiting your approval",
            "detail": str(pending.get("hint") or pending.get("kind") or "Safety confirmation required"),
            "progress": None,
            "step_label": f"Confirm {pending.get('token') or pending.get('kind')}",
            "step_index": None,
            "step_total": None,
            "elapsed_sec": int(max(0, time.time() - float(pending.get("ts") or time.time()))),
            "eta_sec": max(0, 120 - int(max(0, time.time() - float(pending.get("ts") or time.time())))),
            "flow_id": (pending.get("payload") or {}).get("flow_id") if isinstance(pending.get("payload"), dict) else None,
            "phases": ["Plan", "Risk check", "Await confirm", "Execute", "Verify"],
            "phase_index": 2,
        }
    if active:
        a = active[0]
        done = int(a.get("completed_nodes") or 0)
        total = int(a.get("total_nodes") or 0) or max(done, 1)
        progress = int(round(100.0 * done / total)) if total else None
        return {
            "status": "RUNNING",
            "title": a.get("flow_name") or "Active flow",
            "detail": a.get("current_label") or a.get("message") or "Executing workflow…",
            "progress": progress,
            "step_label": a.get("current_label") or "Executing",
            "step_index": done,
            "step_total": total,
            "elapsed_sec": a.get("elapsed_sec"),
            "eta_sec": None,
            "flow_id": a.get("flow_id"),
            "run_id": a.get("run_id"),
            "phases": ["Scan", "Analyze", "Decide", "Act", "Verify"],
            "phase_index": min(4, max(0, done)),
        }
    # Last completed / failed
    if runs:
        r = runs[0]
        st = "COMPLETED" if r.get("ok") else "FAILED"
        if str(r.get("status") or "").upper() == "CANCELLED":
            st = "CANCELLED"
        return {
            "status": st if st != "COMPLETED" else "IDLE",
            "title": r.get("flow_name") or "Last mission",
            "detail": f"Last run {r.get('status')} · {r.get('duration_ms')}ms" if st != "IDLE" else "No mission running. ALTRON is standing by.",
            "progress": 100 if r.get("ok") else None,
            "step_label": r.get("status"),
            "step_index": None,
            "step_total": None,
            "elapsed_sec": None,
            "eta_sec": None,
            "flow_id": r.get("flow_id"),
            "run_id": r.get("id"),
            "phases": ["Observe", "Understand", "Execute"],
            "phase_index": 0 if st == "IDLE" else 2,
            "last_status": st,
        }
    return {
        "status": "IDLE",
        "title": "All systems idle",
        "detail": "No mission running. Command ALTRON from Chat or launch a Flow.",
        "progress": None,
        "step_label": None,
        "step_index": None,
        "step_total": None,
        "elapsed_sec": None,
        "eta_sec": None,
        "flow_id": None,
        "phases": ["Observe", "Understand", "Execute"],
        "phase_index": 0,
    }


def _activity_from_run(run: dict) -> list[dict]:
    events = []
    for nr in (run.get("nodeResults") or [])[-12:]:
        st = str(nr.get("status") or "").upper()
        icon = "ok" if st == "SUCCESS" else ("err" if st == "FAILED" else "run")
        events.append(
            {
                "ts": nr.get("endTime") or nr.get("startTime") or run.get("ended") or run.get("started"),
                "icon": icon,
                "text": nr.get("message") or f"{nr.get('label') or nr.get('type')}: {st}",
                "source": "flow",
                "run_id": run.get("id"),
            }
        )
    p3 = run.get("phase3") if isinstance(run.get("phase3"), dict) else None
    if p3:
        ver = p3.get("verification") or {}
        events.append(
            {
                "ts": run.get("ended"),
                "icon": "ok" if ver.get("ok") else "warn",
                "text": f"Verification {'PASS' if ver.get('ok') else 'FAIL'}",
                "source": "phase3",
                "run_id": run.get("id"),
            }
        )
        for rec in (p3.get("recovery") or [])[-3:]:
            events.append(
                {
                    "ts": rec.get("at") or run.get("ended"),
                    "icon": "warn",
                    "text": rec.get("message") or f"Recovery: {rec.get('action')}",
                    "source": "recovery",
                    "run_id": run.get("id"),
                }
            )
    return events


def _live_activity(settings, runs: list[dict], recent_traces: list[dict], pending: dict | None) -> list[dict]:
    events: list[dict] = []
    if pending:
        events.append(
            {
                "ts": pending.get("ts"),
                "icon": "warn",
                "text": f"Pending approval: {pending.get('hint') or pending.get('kind')}",
                "source": "safety",
            }
        )
    for rmeta in runs[:4]:
        full = flows_engine.get_run(settings, str(rmeta.get("id") or ""))
        if full:
            events.extend(_activity_from_run(full))
        else:
            events.append(
                {
                    "ts": rmeta.get("ended") or rmeta.get("started"),
                    "icon": "ok" if rmeta.get("ok") else "err",
                    "text": f"{rmeta.get('flow_name')}: {rmeta.get('status')}",
                    "source": "flow",
                    "run_id": rmeta.get("id"),
                }
            )
    for row in recent_traces[:8]:
        user = (row.get("user") or "").strip()
        reply = (row.get("reply") or "").strip()
        text = user[:120] if user else (reply[:120] or "Chat turn")
        events.append(
            {
                "ts": row.get("ts"),
                "icon": "chat",
                "text": text,
                "source": "chat",
                "id": row.get("id"),
            }
        )
    # sort newest first loosely
    def key(e: dict) -> float:
        t = e.get("ts")
        if isinstance(t, (int, float)):
            return float(t)
        if isinstance(t, str):
            try:
                return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0
        return 0.0

    events.sort(key=key, reverse=True)
    return events[:40]


def _recent_actions(runs: list[dict], recent_traces: list[dict]) -> list[dict]:
    out = []
    for r in runs[:10]:
        out.append(
            {
                "id": r.get("id"),
                "title": r.get("flow_name") or "Flow run",
                "detail": f"{r.get('status')} · {r.get('duration_ms')}ms",
                "ok": r.get("ok"),
                "ts": r.get("ended") or r.get("started"),
                "kind": "flow",
                "href": f"/flows",
            }
        )
    for row in recent_traces[:8]:
        out.append(
            {
                "id": row.get("id"),
                "title": (row.get("user") or "Chat")[:80],
                "detail": (row.get("reply") or "")[:100],
                "ok": True,
                "ts": row.get("ts"),
                "kind": "chat",
                "href": "/",
            }
        )
    return out[:16]


def _insights(settings, pending: dict | None, runs: list[dict], health: dict) -> list[dict]:
    items = []
    if pending:
        items.append(
            {
                "id": "pending_approval",
                "text": f"Action waiting for confirmation: {pending.get('hint') or pending.get('kind')}",
                "action": "review_approval",
                "href": "#approvals",
                "severity": "high",
            }
        )
    fails = [r for r in runs[:10] if not r.get("ok")]
    if fails:
        items.append(
            {
                "id": "failed_runs",
                "text": f"{len(fails)} recent flow run(s) failed — open Flows to inspect recovery.",
                "action": "open_flows",
                "href": "/flows",
                "severity": "medium",
            }
        )
    if health.get("disk_percent") and health["disk_percent"] >= 90:
        items.append(
            {
                "id": "disk_high",
                "text": f"Disk usage is high ({health['disk_percent']}%). Consider cleanup via Chat.",
                "action": "open_chat",
                "href": "/",
                "severity": "medium",
            }
        )
    if not items:
        items.append(
            {
                "id": "idle_ok",
                "text": "Systems quiet. Ask ALTRON in Chat to organize files, run a flow, or check the PC.",
                "action": "open_chat",
                "href": "/",
                "severity": "low",
            }
        )
    return items


def _altron_state(mission: dict, pending: dict | None, active: list[dict]) -> dict[str, Any]:
    status = str(mission.get("status") or "IDLE")
    return {
        "planning": status in {"IDLE"} and not pending,
        "executing": status == "RUNNING" or bool(active),
        "verifying": status == "RUNNING" and "verify" in str(mission.get("step_label") or "").lower(),
        "awaiting_approval": bool(pending) or status == "NEEDS_APPROVAL",
        "failed": status == "FAILED",
        "idle": status == "IDLE" and not pending and not active,
        "label": status,
    }


def _background_message(mission: dict, pending: dict | None) -> str:
    st = str(mission.get("status") or "IDLE")
    if pending or st == "NEEDS_APPROVAL":
        return "I'm waiting for your approval before continuing a sensitive action."
    if st == "RUNNING":
        return "I'm working in the background to keep your digital world organized and productive."
    if st == "FAILED":
        return "A mission failed. Review Live Activity or Flows for recovery details."
    if st == "CANCELLED":
        return "Mission cancelled. Standing by for your next command."
    return "All clear. I'm standing by — command me from Chat or Voice when you're ready."


def snapshot(settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    now = datetime.now()
    pending = safety.pending(settings.safety_path)
    active = flows_engine.list_active_runs(settings)
    runs = flows_engine.recent_runs(settings, limit=16)
    recent_tr = traces.recent(settings.traces_path, limit=16)
    health = _system_health()
    mission = _current_mission(settings, active, pending, runs)
    workflows = _workflow_counts(settings, active, runs)
    tools = _tools_in_use(settings, active, pending, recent_tr)
    approvals = []
    if pending:
        approvals.append(
            {
                "id": pending.get("token") or "pending",
                "kind": pending.get("kind"),
                "token": pending.get("token"),
                "hint": pending.get("hint"),
                "payload": pending.get("payload") or {},
                "ts": pending.get("ts"),
                "ttl_sec": max(0, int(120 - (time.time() - float(pending.get("ts") or time.time())))),
            }
        )
    security = {
        "secure": True,
        "threats": 0,
        "pending_approvals": len(approvals),
        "conflicts": 0,
        "label": "Secure" if not approvals else "Needs attention",
    }
    return {
        "ok": True,
        "at": time.time(),
        "version": __version__,
        "name": IDENTITY_NAME,
        "greeting": _greeting(now),
        "user_hint": "Commander",
        "datetime": now.strftime("%a, %d %b %Y | %H:%M"),
        "system_online": True,
        "mode": "local",
        "mission": mission,
        "altron_state": _altron_state(mission, pending, active),
        "background_message": _background_message(mission, pending),
        "health": health,
        "workflows": workflows,
        "tools": tools,
        "security": security,
        "insights": _insights(settings, pending, runs, health),
        "activity": _live_activity(settings, runs, recent_tr, pending),
        "recent_actions": _recent_actions(runs, recent_tr),
        "approvals": approvals,
        "links": {
            "chat": "/",
            "flows": "/flows",
            "ide": "/ide",
            "mission": "/mission",
        },
    }


def confirm_pending(settings) -> dict[str, Any]:
    """Confirm pending safety action using the same path as Chat CONFIRM."""
    from altron.adapters import tools

    data = safety.pending(settings.safety_path)
    if not data:
        return {"ok": False, "message": "No pending approval"}
    # Reuse tool dispatch
    msg = tools.dispatch(
        settings,
        "safety_confirm",
        {"kind": data.get("kind"), "payload": data.get("payload") or {}},
        user_text=f"CONFIRM {data.get('token')}",
        ctx={"roots": [], "base": str(Path.home()), "sandbox": False},
    )
    return {"ok": True, "message": str(msg), "kind": data.get("kind")}


def skip_pending(settings) -> dict[str, Any]:
    data = safety.pending(settings.safety_path)
    if not data:
        return {"ok": False, "message": "No pending approval"}
    safety.clear(settings.safety_path)
    return {"ok": True, "message": "Skipped. Pending approval cleared.", "kind": data.get("kind")}
