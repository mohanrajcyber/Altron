from __future__ import annotations

"""Phase 3 — action risk classification for ALTRON FLOWS."""

from typing import Any

# Ordered from safest to most dangerous
RISK_ORDER = ["SAFE", "LOW", "MEDIUM", "HIGH", "DESTRUCTIVE"]

_NODE_RISK: dict[str, str] = {
    "trigger.manual": "SAFE",
    "trigger.schedule": "SAFE",
    "trigger.file_created": "SAFE",
    "trigger.webhook": "LOW",
    "trigger.app_started": "SAFE",
    "files.list": "SAFE",
    "files.read": "LOW",
    "logic.log": "SAFE",
    "notify.log": "SAFE",
    "logic.filter": "SAFE",
    "logic.if": "SAFE",
    "logic.foreach": "SAFE",
    "logic.delay": "SAFE",
    "ai.agent": "LOW",
    "ai.summarize": "LOW",
    "ai.classify": "LOW",
    "data.transform": "SAFE",
    "apps.open_path": "LOW",
    "browser.open_url": "MEDIUM",
    "apps.open_app": "MEDIUM",
    "files.copy": "MEDIUM",
    "files.write": "HIGH",
    "files.rename": "HIGH",
    "files.move": "HIGH",
}


def risk_rank(level: str) -> int:
    level = (level or "SAFE").upper()
    try:
        return RISK_ORDER.index(level)
    except ValueError:
        return 0


def max_risk(*levels: str) -> str:
    best = "SAFE"
    for lv in levels:
        if risk_rank(lv) > risk_rank(best):
            best = (lv or "SAFE").upper()
    return best


def node_risk(ntype: str) -> str:
    return _NODE_RISK.get(str(ntype or ""), "MEDIUM")


def classify_flow(flow: dict) -> dict[str, Any]:
    """Return risk metadata for a flow graph."""
    nodes = flow.get("nodes") or []
    levels = [node_risk(n.get("type")) for n in nodes]
    overall = max_risk(*levels) if levels else "SAFE"
    risky_nodes = [
        {"id": n.get("id"), "type": n.get("type"), "label": n.get("label"), "risk": node_risk(n.get("type"))}
        for n in nodes
        if risk_rank(node_risk(n.get("type"))) >= risk_rank("MEDIUM")
    ]
    requires_confirm = risk_rank(overall) >= risk_rank("HIGH") or bool(
        (flow.get("permissions") or {}).get("requires_confirm")
    )
    # destructive reserved for explicit wipe/delete-everything (policy deny) — move/write = HIGH
    return {
        "risk_level": overall,
        "requires_confirm": requires_confirm,
        "risky_nodes": risky_nodes,
        "phase": 3,
    }


def annotate_flow(flow: dict) -> dict:
    """Mutate a copy-friendly permissions block with risk metadata."""
    meta = classify_flow(flow)
    perms = dict(flow.get("permissions") or {})
    perms["risk_level"] = meta["risk_level"]
    perms["requires_confirm"] = bool(perms.get("requires_confirm") or meta["requires_confirm"])
    perms["risky_nodes"] = meta["risky_nodes"]
    flow["permissions"] = perms
    return flow
