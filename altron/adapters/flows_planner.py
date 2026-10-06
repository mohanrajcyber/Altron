from __future__ import annotations

"""ALTRON FLOWS Phase 2 — AI Workflow Planner.

Natural language → structured plan using ONLY catalog node types.
LLM (ThinkAdapter) preferred; deterministic heuristic fallback.
Plans are validated before materialization — never hallucinated types.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

from altron.adapters import flows_catalog, flows_risk, pc_roots

PLAN_SCHEMA_HINT = """
Return ONLY one JSON object (no markdown) with this shape:
{
  "name": "string",
  "summary": "string",
  "requires_confirm": true/false,
  "explanation": "why these nodes/order",
  "missing": [],
  "nodes": [
    {
      "id": "n1",
      "type": "<catalog type>",
      "label": "string",
      "config": {},
      "position": {"x": 80, "y": 180}
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": "n1",
      "target": "n2",
      "sourceHandle": "default|yes|no",
      "targetHandle": "in"
    }
  ]
}
Rules:
- Use ONLY these node types: __TYPES__
- Include exactly one trigger.* node.
- Prefer linear left-to-right positions (x += 240).
- For If/Else use sourceHandle yes/no.
- For ForEach, body nodes connect from foreach with default handle.
- Risky move/write/rename/copy → requires_confirm true.
- AI Agent config must include schema and strict true when analyzing files.
- Templates like {{item.path}} are allowed in config strings.
"""


def catalog_types() -> list[str]:
    return [n["type"] for n in flows_catalog.NODE_CATALOG if flows_catalog.is_implemented(n["type"])]


def _root_named(settings, name: str) -> str:
    name = (name or "").strip().lower()
    aliases = {
        "download": "Downloads",
        "downloads": "Downloads",
        "desktop": "Desktop",
        "documents": "Documents",
        "docs": "Documents",
    }
    want = aliases.get(name, name)
    for r in pc_roots.list_roots(settings):
        if r["name"].lower() == want.lower():
            return r["path"]
    roots = pc_roots.list_roots(settings)
    return roots[0]["path"] if roots else ""


def validate_plan(settings, plan: dict) -> list[str]:
    """Catalog-only + trusted-path validation for a Phase-2 plan."""
    issues: list[str] = []
    if not isinstance(plan, dict):
        return ["Plan is not an object"]
    nodes = plan.get("nodes") if isinstance(plan.get("nodes"), list) else []
    edges = plan.get("edges") if isinstance(plan.get("edges"), list) else []
    if not nodes:
        issues.append("Plan has no nodes")
        return issues
    allowed = set(catalog_types())
    ids = []
    triggers = 0
    for n in nodes:
        if not isinstance(n, dict) or not n.get("id"):
            issues.append("Node missing id")
            continue
        nid = str(n["id"])
        ids.append(nid)
        ntype = flows_catalog.TYPE_ALIASES.get(str(n.get("type") or ""), str(n.get("type") or ""))
        if ntype not in allowed:
            issues.append(f"Hallucinated or unknown node type: {n.get('type')}")
        if not flows_catalog.is_implemented(ntype):
            issues.append(f"NOT IMPLEMENTED: {ntype}")
        if ntype.startswith("trigger."):
            triggers += 1
        cfg = n.get("config") if isinstance(n.get("config"), dict) else {}
        for key in ("path", "src", "dst_dir", "dst"):
            raw = cfg.get(key)
            if not raw or "{{" in str(raw):
                continue
            if pc_roots.resolve_in_roots(settings, str(raw)) is None:
                parent = str(Path(str(raw)).parent)
                if pc_roots.resolve_in_roots(settings, parent) is None:
                    issues.append(f"Path not in trusted roots: {raw}")
        if ntype == "trigger.schedule" and not str(cfg.get("cron") or "").strip():
            issues.append(f"Schedule node missing cron: {n.get('id')}")
        if ntype == "logic.if" and not str(cfg.get("condition") or "").strip():
            issues.append(f"If/Else missing condition: {n.get('id')}")
    if triggers != 1:
        issues.append(f"Plan must have exactly one trigger (found {triggers})")
    if len(ids) != len(set(ids)):
        issues.append("Duplicate node ids in plan")
    id_set = set(ids)
    for e in edges:
        if not isinstance(e, dict):
            issues.append("Invalid edge")
            continue
        if e.get("source") not in id_set or e.get("target") not in id_set:
            issues.append(f"Edge references missing node: {e.get('source')}→{e.get('target')}")
    return issues


def plan_to_flow(plan: dict) -> dict:
    """Materialize validated plan into persisted flow JSON (source of truth)."""
    nodes = []
    for i, n in enumerate(plan.get("nodes") or []):
        pos = n.get("position") if isinstance(n.get("position"), dict) else {}
        nodes.append(
            {
                "id": str(n["id"]),
                "type": flows_catalog.TYPE_ALIASES.get(str(n.get("type") or ""), str(n.get("type") or "")),
                "label": n.get("label") or n.get("type"),
                "description": n.get("description") or "",
                "position": {"x": float(pos.get("x", 80 + i * 240)), "y": float(pos.get("y", 180))},
                "config": n.get("config") if isinstance(n.get("config"), dict) else {},
            }
        )
    edges = []
    for i, e in enumerate(plan.get("edges") or []):
        edges.append(
            {
                "id": e.get("id") or f"e{i}",
                "source": e["source"],
                "target": e["target"],
                "sourceHandle": e.get("sourceHandle") or "default",
                "targetHandle": e.get("targetHandle") or "in",
                "label": e.get("label") or "",
            }
        )
    perms = {"requires_confirm": bool(plan.get("requires_confirm"))}
    if plan.get("risk_level"):
        perms["risk_level"] = plan.get("risk_level")
    flow = {
        "id": "flow_" + uuid.uuid4().hex[:8],
        "name": plan.get("name") or "Untitled Flow",
        "nodes": nodes,
        "edges": edges,
        "variables": plan.get("variables") if isinstance(plan.get("variables"), dict) else {},
        "permissions": perms,
        "settings": {
            "source": "altron_chat",
            "planner": plan.get("planner") or {"engine": "phase3"},
            "phase": 3,
            "ai_generated": True,
            "explanation": plan.get("explanation") or "",
        },
    }
    return flows_risk.annotate_flow(flow)


def _heuristic_plan(settings, text: str) -> dict:
    """Deterministic catalog-only planner for common organize/scan intents."""
    low = (text or "").lower()
    folder = "Downloads"
    if "desktop" in low:
        folder = "Desktop"
    elif "document" in low:
        folder = "Documents"
    path = _root_named(settings, folder)
    docs = _root_named(settings, "Documents")
    invoices = str(Path(docs) / "Invoices")
    review = str(Path(docs) / "Review")
    other = str(Path(docs) / "Other")

    nightly = bool(re.search(r"\b(every night|nightly|each night|daily at night|every evening)\b", low))
    wants_pdf = "pdf" in low or "organize" in low
    wants_ai = any(k in low for k in ("ai", "analy", "classif", "summar", "content", "rename"))
    wants_move = any(k in low for k in ("move", "organiz", "sort", "correct folder"))
    wants_rename = "rename" in low
    wants_loop = wants_ai or wants_move or wants_rename or "each" in low or "batch" in low
    new_only = bool(re.search(r"\b(new pdf|new file|newly|recent)\b", low))

    nodes: list[dict] = []
    edges: list[dict] = []
    x = 80

    def add(ntype: str, label: str, config: dict | None = None, y: int = 180) -> str:
        nonlocal x
        nid = f"n{len(nodes)+1}"
        nodes.append(
            {
                "id": nid,
                "type": ntype,
                "label": label,
                "config": config or {},
                "position": {"x": x, "y": y},
            }
        )
        x += 240
        return nid

    def link(a: str, b: str, handle: str = "default", label: str = "") -> None:
        edges.append(
            {
                "id": f"e{len(edges)+1}",
                "source": a,
                "target": b,
                "sourceHandle": handle,
                "targetHandle": "in",
                "label": label,
            }
        )

    if nightly:
        trig = add("trigger.schedule", "Every Night", {"cron": "0 21 * * *"})
    else:
        trig = add("trigger.manual", "Manual Trigger", {})

    list_id = add("files.list", f"List {folder}", {"path": path, "pattern": "*.pdf" if wants_pdf and not wants_loop else "", "recursive": "false"})
    link(trig, list_id)

    prev = list_id
    if wants_pdf:
        filt = add("logic.filter", "Filter PDFs", {"pattern": ".pdf"})
        link(prev, filt)
        prev = filt

    requires_confirm = wants_move or wants_rename
    summary_parts = [nodes[0]["label"], "List", "Filter PDFs" if wants_pdf else None]

    if wants_loop:
        fe = add("logic.foreach", "For Each PDF", {"max": "20", "source": "files"})
        link(prev, fe)
        read_id = add("files.read", "Read File", {"path": "{{item.path}}"})
        link(fe, read_id)
        ai_id = add(
            "ai.agent",
            "AI Analyze",
            {
                "prompt": (
                    "Analyze this file. Classify for organization. "
                    "category must be one of: invoice, receipt, report, personal, other. "
                    "suggested_name must be a safe filename ending in .pdf."
                ),
                "input_var": "{{variables.file.text}}",
                "output_var": "ai.result",
                "schema": "category,confidence,summary,suggested_name",
                "strict": "true",
            },
        )
        link(read_id, ai_id)
        conf_if = add("logic.if", "If confidence >= 0.8", {"condition": "confidence >= 0.8"})
        link(ai_id, conf_if)

        # YES: rename (optional) → invoice branch → move
        yes_prev = conf_if
        yes_handle = "yes"
        if wants_rename:
            ren = add(
                "files.rename",
                "Rename From AI",
                {
                    "src": "{{item.path}}",
                    "new_name": "{{variables.ai.result.suggested_name}}",
                },
                y=100,
            )
            link(conf_if, ren, "yes", "Yes")
            yes_prev = ren
            yes_handle = "default"

        inv_if = add("logic.if", "If Invoice", {"condition": "category == 'invoice'"}, y=80)
        link(yes_prev, inv_if, yes_handle, "Yes" if yes_handle == "yes" else "")
        src_expr = "{{last_path}}" if wants_rename else "{{item.path}}"
        move_inv = add("files.move", "Move → Invoices", {"src": src_expr, "dst_dir": invoices}, y=40)
        move_oth = add("files.move", "Move → Other", {"src": src_expr, "dst_dir": other}, y=140)
        link(inv_if, move_inv, "yes", "Yes")
        link(inv_if, move_oth, "no", "No")
        log_ok = add("logic.log", "Log Organized", {"message": "Organized {{item.name}} → ok"}, y=90)
        link(move_inv, log_ok)
        link(move_oth, log_ok)

        # NO low confidence → Review (leave failed/low alone if user asked — still move to Review folder inside trusted roots)
        move_rev = add("files.move", "Move → Review", {"src": "{{item.path}}", "dst_dir": review}, y=300)
        link(conf_if, move_rev, "no", "No")
        log_rev = add("logic.log", "Log Review", {"message": "Low confidence → Review {{item.name}}"}, y=300)
        link(move_rev, log_rev)

        requires_confirm = True
        summary_parts = [
            "Schedule" if nightly else "Manual",
            "List",
            "Filter",
            "ForEach",
            "Read",
            "AI",
            "If",
            "Rename" if wants_rename else None,
            "Move",
            "Log",
        ]
    elif wants_ai:
        ai_id = add(
            "ai.agent",
            "AI Analyze",
            {
                "prompt": "Analyze the file list and summarize PDF contents categories.",
                "schema": "category,confidence,summary,suggested_name",
                "strict": "true",
                "output_var": "ai.result",
            },
        )
        link(prev, ai_id)
        log_id = add("logic.log", "Log", {"message": ""})
        link(ai_id, log_id)
        summary_parts = ["Trigger", "List", "Filter", "AI", "Log"]
    else:
        log_id = add("logic.log", "Log", {"message": ""})
        link(prev, log_id)
        summary_parts = ["Trigger", "List", "Filter" if wants_pdf else None, "Log"]

    name = f"Chat · Organize {folder} PDFs" if wants_move or wants_rename else f"Chat · Scan {folder}"
    if nightly:
        name = f"Nightly · Organize {folder} PDFs"
    if new_only:
        name = name + " (new)"

    steps = [n.get("label") for n in nodes]
    explanation = (
        f"Interpreted request for {folder}. Built catalog-only steps: "
        + " → ".join(str(s) for s in steps)
        + ". Order follows trigger → list → filter → (foreach body) → side effects → log."
    )
    missing: list[str] = []
    if wants_move and not docs:
        missing.append("Documents trusted root for destination folders")

    plan = {
        "name": name,
        "summary": " → ".join(p for p in summary_parts if p),
        "explanation": explanation,
        "missing": missing,
        "requires_confirm": requires_confirm,
        "nodes": nodes,
        "edges": edges,
        "planner": {"engine": "heuristic_v3", "user": text[:500], "nightly": nightly, "phase": 3},
    }
    risk = flows_risk.classify_flow({"nodes": nodes, "permissions": {"requires_confirm": requires_confirm}})
    plan["risk_level"] = risk["risk_level"]
    plan["requires_confirm"] = bool(plan["requires_confirm"] or risk["requires_confirm"])
    return plan


def _llm_plan(settings, text: str) -> dict | None:
    """Ask ThinkAdapter for a catalog-constrained plan. Returns None on failure."""
    from altron.adapters.think import ThinkAdapter

    types = ", ".join(catalog_types())
    hint = PLAN_SCHEMA_HINT.replace("__TYPES__", types)
    roots = pc_roots.list_roots(settings)
    roots_txt = "\n".join(f"- {r['name']}: {r['path']}" for r in roots)
    prompt = (
        f"{hint}\n\nTrusted roots (paths must stay inside these):\n{roots_txt}\n\n"
        f"User request:\n{text}\n"
    )
    try:
        think = ThinkAdapter(settings)
        raw = think.complete([{"role": "user", "content": prompt}])
    except Exception:
        return None
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not obj.get("nodes"):
        return None
    obj["planner"] = {"engine": "llm_v2", "user": text[:500]}
    # Repair common LLM omissions instead of accepting invalid plans
    for n in obj.get("nodes") or []:
        if str(n.get("type") or "") == "trigger.schedule":
            cfg = n.setdefault("config", {})
            if not str(cfg.get("cron") or "").strip():
                cfg["cron"] = "0 21 * * *"
    return obj


def plan_workflow(settings, text: str) -> dict[str, Any]:
    """Full Phase-3 planning pipeline: LLM → validate → else heuristic → validate + enrich."""
    plan = _llm_plan(settings, text)
    if plan is not None:
        issues = validate_plan(settings, plan)
        if not issues:
            return enrich_plan(plan)
        # keep LLM attempt metadata for debugging but fall through
        plan = None

    plan = _heuristic_plan(settings, text)
    issues = validate_plan(settings, plan)
    if issues:
        raise ValueError("Heuristic plan invalid: " + "; ".join(issues))
    return enrich_plan(plan)


def enrich_plan(plan: dict) -> dict:
    """Attach Phase-3 explanation + risk metadata without inventing capabilities."""
    plan = dict(plan or {})
    nodes = plan.get("nodes") or []
    if not plan.get("explanation"):
        labels = [str(n.get("label") or n.get("type")) for n in nodes]
        plan["explanation"] = "Catalog steps: " + " → ".join(labels) if labels else "Empty plan"
    risk = flows_risk.classify_flow({"nodes": nodes, "permissions": {"requires_confirm": plan.get("requires_confirm")}})
    plan["risk_level"] = risk["risk_level"]
    plan["requires_confirm"] = bool(plan.get("requires_confirm") or risk["requires_confirm"])
    plan.setdefault("missing", [])
    planner = dict(plan.get("planner") or {})
    planner.setdefault("phase", 3)
    plan["planner"] = planner
    return plan
