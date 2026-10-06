from __future__ import annotations

"""ALTRON FLOWS Phase 1 — Chat controls Flows via structured plans.

Natural language → intent → validated plan → save/modify/run → observe.
Does NOT bypass Trusted Roots or safety confirmation.
"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from altron.adapters import (
    flows_agent,
    flows_catalog,
    flows_context,
    flows_engine,
    flows_planner,
    flows_risk,
    pc_roots,
    safety,
)

IMPLEMENTED = {
    "trigger.manual",
    "trigger.schedule",
    "trigger.file_created",
    "trigger.webhook",
    "trigger.app_started",
    "files.list",
    "files.read",
    "files.write",
    "files.copy",
    "files.move",
    "files.rename",
    "logic.log",
    "logic.if",
    "logic.filter",
    "logic.delay",
    "logic.foreach",
    "ai.agent",
    "ai.summarize",
    "ai.classify",
    "notify.log",
}


def _trace_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows" / "agi_trace.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _log_trace(settings, record: dict) -> None:
    record = {**record, "ts": time.time()}
    path = _trace_path(settings)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _root_named(settings, name: str) -> str:
    name = (name or "").strip().lower()
    for r in pc_roots.list_roots(settings):
        if r["name"].lower() == name or str(r["path"]).lower().endswith(f"\\{name}"):
            return r["path"]
    # common aliases
    aliases = {"download": "Downloads", "downloads": "Downloads", "desktop": "Desktop", "documents": "Documents", "docs": "Documents"}
    want = aliases.get(name, name)
    for r in pc_roots.list_roots(settings):
        if r["name"].lower() == want.lower():
            return r["path"]
    roots = pc_roots.list_roots(settings)
    return roots[0]["path"] if roots else ""


def _find_flow(settings, query: str) -> dict | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    flows = sorted(flows_engine.list_flows(settings), key=lambda f: f.get("updated") or 0, reverse=True)
    for f in flows:
        if f["id"].lower() == q or f["name"].lower() == q:
            return flows_engine.get_flow(settings, f["id"])
    for f in flows:
        if q in f["name"].lower() or q in f["id"].lower():
            return flows_engine.get_flow(settings, f["id"])
    return None


def parse_intent(text: str) -> dict[str, Any]:
    """Rule-based Phase 1 intent parser (deterministic, no arbitrary code)."""
    raw = (text or "").strip()
    low = raw.lower()

    # Risk denial
    if re.search(r"\b(delete everything|wipe|format c:|rm -rf|/s /q)\b", low):
        return {"intent": "deny", "reason": "Destructive system-wide action is blocked by ALTRON safety policy."}

    if re.search(r"\b(list flows|show flows|what flows)\b", low):
        return {"intent": "list_flows"}

    if m := re.search(r"\b(?:open|show|load)\s+flow\s+(.+)$", low):
        return {"intent": "open_flow", "query": m.group(1).strip(" .\"'")}
    if m := re.search(r"\brun\s+(?:the\s+)?(?:flow\s+)?(.+)$", low):
        q = m.group(1).strip(" .\"'")
        if q not in {"it", "this", "that", "workflow"}:
            return {"intent": "run_flow", "query": q}

    if re.search(r"\b(stop (the )?flow|cancel (the )?flow|stop workflow)\b", low):
        return {"intent": "stop_flow"}

    if re.search(r"\b(last run|run history|show (the )?last execution|why did .*(fail|error))\b", low):
        return {"intent": "last_run", "query": raw}

    if re.search(r"\b(save (this |the )?flow|save workflow)\b", low):
        return {"intent": "save_hint"}

    if re.search(r"\b(undo( last)?( change| edit)?|restore previous version)\b", low):
        return {"intent": "undo_flow", "text": raw}
    if re.search(r"\b(duplicate|clone)\b.+\b(flow|workflow)\b|\bduplicate (this|the) (flow|workflow)\b", low):
        return {"intent": "duplicate_flow", "text": raw}
    if m := re.search(r"\brename (?:the )?(?:flow|workflow)\s+(?:to\s+)?(.+)$", raw, flags=re.I):
        return {"intent": "rename_flow", "name": m.group(1).strip(" .\"'")}

    # Modifications first when clearly editing an existing graph
    if re.search(r"\b(add|insert)\b.+\b(ai|agent|analysis|filter|log|delay|loop|node|if|condition)\b", low) or re.search(
        r"\b(remove|delete)\b.+\b(node|log|ai|filter|move|step)\b", low
    ) or re.search(r"\b(only continue|continue when|when .+ count|greater than|if .+ count|confidence)\b", low) or re.search(
        r"\b(connect|wire)\b.+\b(node|to)\b", low
    ) or re.search(r"\b(modify|edit)\b.+\b(node|flow|workflow|step)\b", low) or re.search(
        r"\b(make it run every night|schedule (it )?nightly|run every night)\b", low
    ) or re.search(r"\bbefore\b.+\bai\b", low) or re.search(
        r"\b(change|set|update)\b.+\b(folder|path|filter|config)\b", low
    ) or re.search(r"\b(only|filter).+\bpdf\b", low) or re.search(r"\b(move them to|destination)\b", low):
        return {"intent": "modify_flow", "text": raw}

    # Creation wins for nightly scan/organize and explicit create phrases
    create = bool(
        re.search(
            r"\b(create|make|build|generate)\b.+\b(flow|workflow)\b|\borganize\b|\bscan\b.+\b(folder|downloads|desktop|pdf)",
            low,
        )
        or re.search(r"\bpdf\b.+\b(invoice|organ|classif)\b", low)
        or re.search(r"\b(list|scan|check)\b.+\b(downloads|desktop|documents)\b", low)
        or re.search(r"\b(every night|nightly).+\b(scan|check|find|organiz|analy)\b", low)
    )
    if create or re.search(r"\b(classify|invoice)\b.+\b(pdf|download|desktop)\b", low):
        return {"intent": "create_workflow", "text": raw}

    if re.search(r"\b(rerun|re-run|run again|run it again)\b", low):
        return {"intent": "run_flow", "query": "it"}

    # Remaining classify/create-ish
    if re.search(r"\b(classify|invoice)\b", low):
        return {"intent": "create_workflow", "text": raw}

    if re.search(r"\b(flows?|workflow)\b", low):
        return {"intent": "flows_help", "text": raw}

    return {"intent": "unknown", "text": raw}


def plan_from_text(settings, text: str) -> dict[str, Any]:
    """Build a structured workflow plan from NL (template + heuristics)."""
    low = (text or "").lower()
    folder = "Downloads"
    if "desktop" in low:
        folder = "Desktop"
    elif "document" in low:
        folder = "Documents"
    path = _root_named(settings, folder)

    wants_pdf = "pdf" in low
    wants_ai = any(k in low for k in ("classify", "ai", "invoice", "summar", "analy"))
    wants_move = "move" in low
    wants_loop = any(k in low for k in ("each", "every file", "for each", "loop"))
    wants_filter = wants_pdf or "filter" in low or "only" in low
    invoice = "invoice" in low

    steps: list[dict] = [{"node": "trigger.manual", "label": "Manual Trigger"}]
    steps.append(
        {
            "node": "files.list",
            "label": f"List {folder}",
            "config": {"path": path, "pattern": "*.pdf" if wants_pdf and not wants_filter else "", "recursive": "false"},
        }
    )
    if wants_filter:
        steps.append({"node": "logic.filter", "label": "Filter", "config": {"pattern": ".pdf" if wants_pdf else "."}})

    if wants_loop and wants_ai:
        steps.append({"node": "logic.foreach", "label": "For Each File", "config": {"source": "files"}})
        steps.append(
            {
                "node": "ai.classify" if invoice or "classif" in low else "ai.agent",
                "label": "AI Classify" if invoice or "classif" in low else "AI Agent",
                "config": {
                    "prompt": "Classify this file for organization. If invoice-like, say invoice; else other.",
                    "labels": "invoice,other" if invoice or "classif" in low else "",
                    "input_var": "{{item.name}}",
                    "output_var": "ai.label" if invoice or "classif" in low else "ai.result",
                },
            }
        )
        if wants_move:
            dest = _root_named(settings, "Documents")
            inv = str(Path(dest) / "Invoices") if invoice else str(Path(dest) / "Reports")
            steps.append(
                {
                    "node": "files.move",
                    "label": "Move File",
                    "config": {"src": "{{item.path}}", "dst_dir": inv},
                    "requires_confirm": True,
                }
            )
        steps.append({"node": "logic.log", "label": "Log", "config": {"message": ""}})
    elif wants_ai:
        steps.append(
            {
                "node": "ai.agent" if not (invoice or "classif" in low) else "ai.classify",
                "label": "AI Agent" if not (invoice or "classif" in low) else "Classify",
                "config": {
                    "prompt": "From this file list, classify PDFs. Mark likely invoices vs other.",
                    "labels": "invoice,other,mixed",
                    "input_var": "",
                    "output_var": "ai.result",
                    "schema": "classification,confidence,summary",
                },
            }
        )
        steps.append({"node": "logic.log", "label": "Log", "config": {"message": ""}})
    else:
        steps.append({"node": "logic.log", "label": "Log", "config": {"message": ""}})

    name = "Chat PDF Organizer" if wants_pdf else f"Chat · Scan {folder}"
    if invoice:
        name = "Chat Invoice Organizer"
    return {
        "intent": "create_workflow",
        "name": name,
        "folder": folder,
        "path": path,
        "steps": steps,
        "requires_confirm": any(s.get("requires_confirm") for s in steps) or wants_move,
        "summary": " → ".join(s.get("label") or s["node"] for s in steps),
    }


def plan_to_flow(plan: dict) -> dict:
    """Convert structured plan to flow JSON v1."""
    nodes: list[dict] = []
    edges: list[dict] = []
    x, y = 80, 180
    prev = None
    for i, step in enumerate(plan.get("steps") or []):
        ntype = step.get("node") or ""
        if ntype not in IMPLEMENTED and not flows_catalog.is_implemented(ntype):
            raise ValueError(f"NOT IMPLEMENTED node in plan: {ntype}")
        nid = f"n{i+1}"
        nodes.append(
            {
                "id": nid,
                "type": ntype,
                "label": step.get("label") or ntype,
                "description": step.get("description") or "",
                "position": {"x": x, "y": y},
                "config": step.get("config") if isinstance(step.get("config"), dict) else {},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"e{i}",
                    "source": prev,
                    "target": nid,
                    "sourceHandle": "default",
                    "targetHandle": "in",
                }
            )
        prev = nid
        x += 260
    return {
        "id": "flow_" + uuid.uuid4().hex[:8],
        "name": plan.get("name") or "Untitled Flow",
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "permissions": {"requires_confirm": bool(plan.get("requires_confirm"))},
        "settings": {"source": "altron_chat"},
    }


def _new_node_id(nodes: list) -> str:
    return "n" + uuid.uuid4().hex[:6]


def _insert_after(flow: dict, anchor_id: str, node: dict, handle: str = "default") -> None:
    """Insert node after anchor; rewire outgoing edges from anchor to leave the new node."""
    nodes = flow.setdefault("nodes", [])
    edges = flow.setdefault("edges", [])
    nodes.append(node)
    nid = node["id"]
    for e in edges:
        if e.get("source") == anchor_id and (e.get("sourceHandle") or "default") == handle:
            e["source"] = nid
    edges.append(
        {
            "id": "e" + uuid.uuid4().hex[:5],
            "source": anchor_id,
            "target": nid,
            "sourceHandle": handle,
            "targetHandle": "in",
        }
    )


def modify_flow_from_text(settings, flow: dict, text: str) -> dict:
    """Apply NL modifications to an existing flow (create/add/remove/modify/connect/condition)."""
    low = (text or "").lower()
    flow = json.loads(json.dumps(flow))  # deep copy
    nodes = flow.get("nodes") or []

    # change folder
    m = re.search(r"(?:folder|path).*\b(?:to|as)\b\s+(\w+)", low)
    if not m:
        m = re.search(r"\b(?:use|set)\s+(downloads|desktop|documents)\b", low)
    if m:
        folder = m.group(1)
        path = _root_named(settings, folder)
        for n in nodes:
            if str(n.get("type")).startswith("files.list"):
                n.setdefault("config", {})["path"] = path
                n["label"] = f"List {folder.title()}"

    # filter pdf only / change filter pattern
    if "pdf" in low and ("only" in low or "filter" in low) and "count" not in low:
        filt = next((n for n in nodes if n.get("type") == "logic.filter"), None)
        if filt:
            filt.setdefault("config", {})["pattern"] = ".pdf"
        else:
            list_n = next((n for n in nodes if n.get("type") == "files.list"), None)
            if list_n:
                nid = _new_node_id(nodes)
                _insert_after(
                    flow,
                    list_n["id"],
                    {
                        "id": nid,
                        "type": "logic.filter",
                        "label": "Filter PDF",
                        "position": {"x": list_n["position"]["x"] + 240, "y": list_n["position"]["y"]},
                        "config": {"pattern": ".pdf"},
                    },
                )
                nodes = flow["nodes"]

    # destination
    m = re.search(r"move (?:them |it )?(?:to|into)\s+(.+)$", low)
    if m:
        dest_raw = m.group(1).strip(" .\"'")
        parts = re.split(r"[\\/]", dest_raw)
        base = _root_named(settings, parts[0] if parts else "Documents")
        dest = str(Path(base).joinpath(*parts[1:])) if len(parts) > 1 else base
        for n in nodes:
            if n.get("type") == "files.move":
                n.setdefault("config", {})["dst_dir"] = dest

    # add AI analysis / AI agent after PDF scan (list or filter)
    if re.search(r"\badd\b.+\b(ai agent|ai analysis|ai step|analysis step)\b", low) or re.search(
        r"\badd an ai\b", low
    ):
        anchor = next((n for n in reversed(nodes) if n.get("type") in {"logic.filter", "files.list"}), None)
        has_ai = any(str(n.get("type", "")).startswith("ai.") for n in nodes)
        if anchor and not has_ai:
            nid = _new_node_id(nodes)
            _insert_after(
                flow,
                anchor["id"],
                {
                    "id": nid,
                    "type": "ai.agent",
                    "label": "AI Analysis",
                    "position": {"x": anchor["position"]["x"] + 240, "y": anchor["position"]["y"]},
                    "config": {
                        "prompt": "Analyze the PDF scan results. Return structured JSON.",
                        "input_var": "",
                        "output_var": "ai.result",
                        "schema": "category,confidence,summary,suggested_name",
                        "strict": "true",
                    },
                },
            )
            nodes = flow["nodes"]

    # Add PDF filter BEFORE AI
    if re.search(r"\b(add|insert)\b.+\b(pdf )?filter\b.+\bbefore\b.+\bai\b", low) or re.search(
        r"\bfilter before ai\b|\bbefore ai\b.+\bfilter\b", low
    ):
        ai = next((n for n in nodes if str(n.get("type", "")).startswith("ai.")), None)
        if ai and not any(n.get("type") == "logic.filter" for n in nodes):
            inbound = [e for e in (flow.get("edges") or []) if e.get("target") == ai["id"]]
            nid = _new_node_id(nodes)
            flow.setdefault("nodes", []).append(
                {
                    "id": nid,
                    "type": "logic.filter",
                    "label": "Filter PDF",
                    "position": {"x": max(0, ai["position"]["x"] - 120), "y": ai["position"]["y"]},
                    "config": {"pattern": ".pdf"},
                }
            )
            for e in inbound:
                e["target"] = nid
            flow.setdefault("edges", []).append(
                {
                    "id": "e" + uuid.uuid4().hex[:5],
                    "source": nid,
                    "target": ai["id"],
                    "sourceHandle": "default",
                    "targetHandle": "in",
                }
            )
            nodes = flow["nodes"]

    # Make it run every night
    if re.search(r"\b(every night|nightly|make it run every night|schedule (it )?nightly)\b", low):
        trig = next((n for n in nodes if str(n.get("type", "")).startswith("trigger.")), None)
        if trig:
            trig["type"] = "trigger.schedule"
            trig["label"] = "Every Night"
            trig.setdefault("config", {})["cron"] = "0 21 * * *"

    # Rename workflow (also handled as intent, but allow in modify text)
    m = re.search(r"\brename (?:the )?(?:flow|workflow)\s+(?:to\s+)?(.+)$", text, flags=re.I)
    if m:
        flow["name"] = m.group(1).strip(" .\"'")[:120]

    # Only continue when PDF count > 0  → insert If/Else after scan
    if re.search(r"\b(only continue|continue when|when .+count|greater than\s*0|count\s*>\s*0)\b", low) or re.search(
        r"\bif\b.+\b(pdf )?count\b", low
    ):
        if not any(n.get("type") == "logic.if" for n in nodes):
            anchor = next((n for n in reversed(nodes) if n.get("type") in {"logic.filter", "files.list"}), None)
            if anchor:
                cond = (
                    "filter.file_count > 0"
                    if any(n.get("type") == "logic.filter" for n in nodes)
                    else "list.file_count > 0"
                )
                nid = _new_node_id(nodes)
                if_node = {
                    "id": nid,
                    "type": "logic.if",
                    "label": "If PDF count > 0",
                    "position": {"x": anchor["position"]["x"] + 240, "y": anchor["position"]["y"]},
                    "config": {"condition": cond},
                }
                outgoing = [e for e in (flow.get("edges") or []) if e.get("source") == anchor["id"]]
                flow.setdefault("nodes", []).append(if_node)
                for e in outgoing:
                    e["source"] = nid
                    e["sourceHandle"] = "yes"
                    e["label"] = "Yes"
                flow.setdefault("edges", []).append(
                    {
                        "id": "e" + uuid.uuid4().hex[:5],
                        "source": anchor["id"],
                        "target": nid,
                        "sourceHandle": "default",
                        "targetHandle": "in",
                    }
                )
                skip_id = _new_node_id(flow["nodes"])
                flow["nodes"].append(
                    {
                        "id": skip_id,
                        "type": "logic.log",
                        "label": "Skip (no PDFs)",
                        "position": {"x": if_node["position"]["x"] + 240, "y": if_node["position"]["y"] + 120},
                        "config": {"message": "No PDFs — skipped AI/downstream"},
                    }
                )
                flow["edges"].append(
                    {
                        "id": "e" + uuid.uuid4().hex[:5],
                        "source": nid,
                        "target": skip_id,
                        "sourceHandle": "no",
                        "targetHandle": "in",
                        "label": "No",
                    }
                )
                nodes = flow["nodes"]

    # Add IF on confidence (Phase 2)
    # Supports: "add an IF where confidence is below 0.8" / "confidence >= 0.8"
    if (
        re.search(r"\badd\b.+\b(if|condition)\b", low)
        or re.search(r"\bif\b.+\bconfidence\b", low)
        or re.search(r"\bconfidence\b.+\b(below|under|less than|<|>=|>)\b", low)
    ) and "count" not in low:
        ai = next((n for n in nodes if str(n.get("type", "")).startswith("ai.")), None)
        m_below = re.search(r"confidence\s*(?:is\s+)?(?:below|under|less than|<)\s*(0?\.\d+|\d+(?:\.\d+)?)", low)
        m_above = re.search(r"confidence\s*(?:>=|>|at least|above)\s*(0?\.\d+|\d+(?:\.\d+)?)", low)
        if m_below:
            thresh = m_below.group(1)
            cond = f"confidence < {thresh}"
            label = f"If confidence < {thresh}"
        elif m_above:
            thresh = m_above.group(1)
            op = ">=" if ">=" in low or "at least" in low else ">"
            cond = f"confidence {op} {thresh}"
            label = f"If confidence {op} {thresh}"
        else:
            cond = "confidence >= 0.8"
            label = "If confidence >= 0.8"
        existing_conf_if = any(
            n.get("type") == "logic.if"
            and "confidence" in str((n.get("config") or {}).get("condition") or "").lower()
            for n in nodes
        )
        if ai and not existing_conf_if:
            nid = _new_node_id(nodes)
            if_node = {
                "id": nid,
                "type": "logic.if",
                "label": label,
                "position": {"x": ai["position"]["x"] + 240, "y": ai["position"]["y"]},
                "config": {"condition": cond},
            }
            outgoing = [e for e in (flow.get("edges") or []) if e.get("source") == ai["id"]]
            flow.setdefault("nodes", []).append(if_node)
            for e in outgoing:
                e["source"] = nid
                e["sourceHandle"] = "yes"
                e["label"] = "Yes"
            flow.setdefault("edges", []).append(
                {
                    "id": "e" + uuid.uuid4().hex[:5],
                    "source": ai["id"],
                    "target": nid,
                    "sourceHandle": "default",
                    "targetHandle": "in",
                }
            )
            # NO branch log if none
            if not any(e.get("source") == nid and (e.get("sourceHandle") or "") == "no" for e in flow.get("edges") or []):
                skip_id = _new_node_id(flow["nodes"])
                flow["nodes"].append(
                    {
                        "id": skip_id,
                        "type": "logic.log",
                        "label": "Low confidence path",
                        "position": {"x": if_node["position"]["x"] + 240, "y": if_node["position"]["y"] + 120},
                        "config": {"message": "Branch NO — confidence condition false"},
                    }
                )
                flow["edges"].append(
                    {
                        "id": "e" + uuid.uuid4().hex[:5],
                        "source": nid,
                        "target": skip_id,
                        "sourceHandle": "no",
                        "targetHandle": "in",
                        "label": "No",
                    }
                )
            nodes = flow["nodes"]

    # remove log / ai / filter / move node (repair edges)
    for kind, ntype_match in (
        ("log", {"logic.log", "notify.log"}),
        ("ai", None),
        ("filter", {"logic.filter"}),
        ("move", {"files.move"}),
    ):
        if re.search(rf"\b(remove|delete)\b.+\b{kind}\b", low):
            victims = []
            for n in list(nodes):
                t = str(n.get("type") or "")
                if ntype_match and t in ntype_match:
                    victims.append(n)
                elif kind == "ai" and t.startswith("ai."):
                    victims.append(n)
            for ln in victims:
                parents = [e for e in (flow.get("edges") or []) if e.get("target") == ln["id"]]
                children = [e for e in (flow.get("edges") or []) if e.get("source") == ln["id"]]
                nodes = [n for n in nodes if n["id"] != ln["id"]]
                flow["edges"] = [
                    e for e in (flow.get("edges") or []) if e.get("source") != ln["id"] and e.get("target") != ln["id"]
                ]
                for p in parents:
                    for c in children:
                        flow["edges"].append(
                            {
                                "id": "e" + uuid.uuid4().hex[:5],
                                "source": p["source"],
                                "target": c["target"],
                                "sourceHandle": p.get("sourceHandle") or "default",
                                "targetHandle": "in",
                            }
                        )

    # connect node A to node B (by label substring)
    m = re.search(r"\bconnect\b\s+(.+?)\s+to\s+(.+)$", low)
    if m:
        a_q, b_q = m.group(1).strip(" .\"'"), m.group(2).strip(" .\"'")
        a = next((n for n in nodes if a_q in str(n.get("label") or "").lower() or a_q in str(n.get("id")).lower()), None)
        b = next((n for n in nodes if b_q in str(n.get("label") or "").lower() or b_q in str(n.get("id")).lower()), None)
        if a and b:
            flow.setdefault("edges", []).append(
                {
                    "id": "e" + uuid.uuid4().hex[:5],
                    "source": a["id"],
                    "target": b["id"],
                    "sourceHandle": "default",
                    "targetHandle": "in",
                }
            )

    # modify node prompt/config: set prompt on AI node
    m = re.search(r"\b(?:set|change)\s+prompt\s+to\s+(.+)$", low)
    if m:
        prompt = m.group(1).strip(" .\"'")
        for n in nodes:
            if str(n.get("type", "")).startswith("ai."):
                n.setdefault("config", {})["prompt"] = prompt

    flow["nodes"] = nodes
    return flow


def validate_plan_or_flow(settings, flow: dict) -> list[str]:
    issues: list[str] = []
    nodes = flow.get("nodes") or []
    edges = flow.get("edges") or []
    ids = [n.get("id") for n in nodes if n.get("id")]
    if not nodes:
        issues.append("Flow has no nodes.")
    if len(ids) != len(set(ids)):
        issues.append("Duplicate node ids.")
    id_set = set(ids)
    for e in edges:
        if e.get("source") not in id_set:
            issues.append(f"Edge source missing: {e.get('source')}")
        if e.get("target") not in id_set:
            issues.append(f"Edge target missing: {e.get('target')}")
        if e.get("source") == e.get("target"):
            issues.append(f"Self-edge on {e.get('source')}")
    triggers = [n for n in nodes if str(n.get("type", "")).startswith("trigger.")]
    if not triggers:
        issues.append("Flow has no trigger node.")
    for n in nodes:
        ntype = flows_catalog.TYPE_ALIASES.get(n.get("type"), n.get("type"))
        if not flows_catalog.is_implemented(str(ntype)):
            issues.append(f"Node {n.get('label')} ({ntype}) is NOT IMPLEMENTED.")
        cfg = n.get("config") or {}
        for key in ("path", "src", "dst_dir"):
            if cfg.get(key) and "{{" not in str(cfg.get(key)):
                if pc_roots.resolve_in_roots(settings, str(cfg.get(key))) is None:
                    parent = str(Path(str(cfg.get(key))).parent)
                    if pc_roots.resolve_in_roots(settings, parent) is None:
                        issues.append(f"Path not in trusted roots: {cfg.get(key)}")
        if ntype == "trigger.schedule" and not str(cfg.get("cron") or "").strip():
            issues.append(f"Schedule node {n.get('label')} missing cron.")
        if ntype == "logic.if" and not str(cfg.get("condition") or "").strip():
            issues.append(f"If/Else node {n.get('label')} missing condition.")
    return issues


def summarize_run(run: dict) -> str:
    ok = run.get("ok")
    status = run.get("status")
    ms = run.get("duration_ms")
    nodes = run.get("nodes") or {}
    list_out = {}
    for v in nodes.values():
        out = v.get("output") if isinstance(v, dict) else None
        if isinstance(out, dict) and "file_count" in out:
            list_out = out
            break
    filter_out = {}
    for v in nodes.values():
        out = v.get("output") if isinstance(v, dict) else None
        if isinstance(out, dict) and "pattern" in out and "files" in out:
            filter_out = out
    ai_text = ""
    for v in nodes.values():
        out = v.get("output") if isinstance(v, dict) else None
        if isinstance(out, dict) and out.get("text"):
            ai_text = str(out.get("text"))[:400]
            break
    lines = [
        f"{'Completed' if ok else 'Failed'}.",
        f"Status: {status}",
        f"Duration: {ms}ms",
    ]
    if list_out:
        lines.append(f"Scanned: {list_out.get('count', 0)} entries / {list_out.get('file_count', 0)} files in {list_out.get('folder')}")
    if filter_out:
        lines.append(f"Filtered: {filter_out.get('file_count', filter_out.get('count', 0))} (pattern={filter_out.get('pattern')})")
    if ai_text:
        lines.append(f"AI: {ai_text}")
    errs = [v.get("error") for v in nodes.values() if isinstance(v, dict) and v.get("error")]
    lines.append(f"Errors: {len(errs)}")
    if errs:
        lines.append(f"Error detail: {errs[0]}")
    p3 = run.get("phase3") if isinstance(run.get("phase3"), dict) else None
    if p3:
        lines.append(f"Autonomous attempts: {p3.get('attempts')}")
        if p3.get("retries"):
            lines.append(f"Retries: {len(p3.get('retries') or [])}")
        ver = p3.get("verification") or {}
        lines.append(f"Verification: {'PASS' if ver.get('ok') else 'FAIL'}")
        rec = p3.get("recovery") or []
        if rec:
            last = rec[-1]
            lines.append(f"Recovery: {last.get('action')} — {last.get('message') or ''}")
        if p3.get("checkpoint_id"):
            lines.append(f"Checkpoint: {p3.get('checkpoint_id')}")
        if p3.get("risk"):
            lines.append(f"Risk: {p3.get('risk')}")
    return "\n".join(lines)


def handle(settings, user_text: str, args: dict | None = None) -> str:
    """Main Chat → Flows entry. Returns user-facing message."""
    args = args or {}
    text = str(args.get("text") or user_text or "").strip()
    intent = parse_intent(text)
    _log_trace(settings, {"phase": "intent", "user": text, "intent": intent})

    if intent.get("intent") == "deny":
        return f"Denied.\n{intent.get('reason')}"

    if intent.get("intent") == "list_flows":
        flows = flows_engine.list_flows(settings)
        if not flows:
            return "No flows saved yet."
        lines = ["ALTRON FLOWS:"]
        for f in flows:
            lines.append(f"- {f['name']} ({f['id']}) · {f.get('node_count', 0)} nodes")
        lines.append("\nSay: run flow <name>  |  open flows  |  create a workflow that …")
        return "\n".join(lines)

    if intent.get("intent") == "open_flow":
        flow = _find_flow(settings, intent.get("query") or "")
        if not flow:
            return f"Flow not found: {intent.get('query')}"
        flows_engine.open_flows_ui(settings)
        return f"Opened Flows UI.\nActive flow to load: {flow.get('name')} ({flow.get('id')})"

    if intent.get("intent") == "stop_flow":
        # stop most recent active — best-effort via last run id in trace not available;
        runs = flows_engine.recent_runs(settings, limit=1)
        if not runs:
            return "No recent run to stop."
        rid = runs[0].get("id")
        res = flows_engine.stop_run(str(rid))
        return res.get("message") or str(res)

    if intent.get("intent") == "last_run":
        runs = flows_engine.recent_runs(settings, limit=1)
        if not runs:
            return "No runs yet."
        run = flows_engine.get_run(settings, str(runs[0]["id"]))
        if not run:
            return "Run record missing."
        return summarize_run(run)

    if intent.get("intent") == "run_flow":
        q = (intent.get("query") or "").strip().lower()
        flow = None
        if q in {"", "it", "this", "that", "workflow", "again", "the workflow", "the flow"}:
            flows = flows_engine.list_flows(settings)
            for f in flows:
                g = flows_engine.get_flow(settings, f["id"])
                if g and (g.get("settings") or {}).get("source") == "altron_chat":
                    flow = g
                    break
            if flow is None and flows:
                flow = flows_engine.get_flow(settings, flows[0]["id"])
        else:
            flow = _find_flow(settings, intent.get("query") or "")
        if not flow:
            return f"Flow not found: {intent.get('query')}\nSay 'list flows' to see names."
        issues = validate_plan_or_flow(settings, flow)
        if issues:
            return "Cannot run — validation failed:\n- " + "\n- ".join(issues)
        flows_risk.annotate_flow(flow)
        # confirmation for move/write heavy flows or permissions flag
        risky = bool((flow.get("permissions") or {}).get("requires_confirm"))
        risky = risky or any(
            str(n.get("type")) in {"files.move", "files.write", "files.copy", "files.rename"}
            for n in flow.get("nodes") or []
        )
        risk_level = (flow.get("permissions") or {}).get("risk_level") or "SAFE"
        if risky or flows_risk.risk_rank(str(risk_level)) >= flows_risk.risk_rank("HIGH"):
            return safety.request(
                settings.safety_path,
                "flow_run",
                {"flow_id": flow["id"]},
                f"Run flow '{flow.get('name')}' [{risk_level}] which may move/write files under Trusted Roots?",
            )
        run = flows_agent.run_autonomous(settings, flow["id"])
        ctx = flows_context.build_context(settings, user_command=text, flow=flow, run=run)
        flows_context.persist_context(settings, flow["id"], ctx)
        _log_trace(
            settings,
            {
                "phase": "run_autonomous",
                "flow_id": flow["id"],
                "ok": run.get("ok"),
                "status": run.get("status"),
                "phase3": run.get("phase3"),
            },
        )
        return summarize_run(run)

    if intent.get("intent") == "modify_flow":
        # modify most recently updated chat-created flow, else newest flow
        flows = sorted(flows_engine.list_flows(settings), key=lambda f: f.get("updated") or 0, reverse=True)
        if not flows:
            return "No flow to modify. Create one first."
        target = None
        for f in flows:
            g = flows_engine.get_flow(settings, f["id"])
            if g and (g.get("settings") or {}).get("source") == "altron_chat":
                target = g
                break
        if target is None:
            target = flows_engine.get_flow(settings, flows[0]["id"])
        assert target is not None
        updated = modify_flow_from_text(settings, target, text)
        issues = validate_plan_or_flow(settings, updated)
        if issues:
            return "Modify validation failed:\n- " + "\n- ".join(issues)
        saved = flows_engine.save_flow(settings, updated)
        _log_trace(settings, {"phase": "modify", "flow_id": saved.get("id"), "user": text})
        return (
            f"Updated flow: {saved.get('name')} ({saved.get('id')})\n"
            f"Nodes: {len(saved.get('nodes') or [])}\n"
            f"Types: {', '.join(str(n.get('type')) for n in (saved.get('nodes') or []))}\n"
            f"Say 'run flow {saved.get('name')}' to execute."
        )

    if intent.get("intent") == "undo_flow":
        target = _latest_chat_flow(settings)
        if not target:
            return "No flow to undo."
        restored = flows_engine.undo_flow(settings, target["id"])
        if not restored:
            return "No previous version available to undo."
        return f"Restored previous version of '{restored.get('name')}' ({restored.get('id')}). Nodes: {len(restored.get('nodes') or [])}"

    if intent.get("intent") == "duplicate_flow":
        target = _latest_chat_flow(settings)
        if not target:
            return "No flow to duplicate."
        dup = flows_engine.duplicate_flow(settings, target["id"])
        if not dup:
            return "Duplicate failed."
        return f"Duplicated → {dup.get('name')} ({dup.get('id')})"

    if intent.get("intent") == "rename_flow":
        target = _latest_chat_flow(settings)
        if not target:
            return "No flow to rename."
        target["name"] = str(intent.get("name") or target.get("name"))[:120]
        saved = flows_engine.save_flow(settings, target)
        return f"Renamed workflow → {saved.get('name')} ({saved.get('id')})"

    if intent.get("intent") == "create_workflow":
        try:
            plan = flows_planner.plan_workflow(settings, text)
            flow = flows_planner.plan_to_flow(plan)
            issues = validate_plan_or_flow(settings, flow)
            if issues:
                raise ValueError("; ".join(issues))
        except ValueError as exc:
            # fallback to Phase-1 / heuristic planner
            _log_trace(settings, {"phase": "plan_fallback", "error": str(exc), "user": text})
            try:
                plan = flows_planner._heuristic_plan(settings, text)  # noqa: SLF001
                issues = flows_planner.validate_plan(settings, plan)
                if issues:
                    plan = plan_from_text(settings, text)
                    flow = plan_to_flow(plan)
                else:
                    flow = flows_planner.plan_to_flow(plan)
            except ValueError as exc2:
                return f"Plan rejected: {exc2}"
        _log_trace(settings, {"phase": "plan_v2", "plan": {k: plan.get(k) for k in ("name", "summary", "requires_confirm", "planner")}, "user": text})
        issues = validate_plan_or_flow(settings, flow)
        if issues:
            return "Plan validation failed:\n- " + "\n- ".join(issues)

        saved = flows_engine.save_flow(settings, flow)
        _log_trace(settings, {"phase": "save", "flow_id": saved.get("id")})
        engine = (plan.get("planner") or {}).get("engine", "phase3")
        expl = flows_agent.explain_plan(plan)
        msg = (
            f"Created workflow: {saved.get('name')} ({saved.get('id')})\n"
            f"Plan: {plan.get('summary')}\n"
            f"Risk: {plan.get('risk_level') or (saved.get('permissions') or {}).get('risk_level')}\n"
            f"Planner: {engine}\n"
            f"Nodes: {len(saved.get('nodes') or [])}\n"
            f"{expl}\n"
            f"Open Flows UI to inspect the canvas.\n"
        )
        risk_level = plan.get("risk_level") or (saved.get("permissions") or {}).get("risk_level") or "SAFE"
        if plan.get("requires_confirm") or any(
            str(n.get("type")) in {"files.move", "files.write", "files.copy", "files.rename"} for n in saved.get("nodes") or []
        ) or flows_risk.risk_rank(str(risk_level)) >= flows_risk.risk_rank("HIGH"):
            msg += safety.request(
                settings.safety_path,
                "flow_run",
                {"flow_id": saved["id"]},
                f"Execute '{saved.get('name')}' [{risk_level}] now? It may move/rename/write files under Trusted Roots.",
            )
        else:
            msg += f"Say: run flow {saved.get('name')}"
        flows_engine.open_flows_ui(settings)
        return msg

    if intent.get("intent") == "flows_help":
        return (
            "ALTRON FLOWS Phase 3 commands:\n"
            "- create a workflow that scans Downloads for PDFs and organizes them\n"
            "- every night check Downloads, find new PDFs, analyze, rename, move\n"
            "- add a PDF filter before AI / remove the move step\n"
            "- make it run every night / rename the workflow to …\n"
            "- undo / duplicate this workflow\n"
            "- run flow <name> / show last run / list flows\n"
            "- autonomous execute → observe → verify → recover\n"
        )

    return (
        "I can control ALTRON FLOWS from chat.\n"
        "Try: create a workflow that scans my Downloads for PDF files and logs the results.\n"
        "Or: list flows"
    )


def _latest_chat_flow(settings) -> dict | None:
    flows = sorted(flows_engine.list_flows(settings), key=lambda f: f.get("updated") or 0, reverse=True)
    for f in flows:
        g = flows_engine.get_flow(settings, f["id"])
        if g and (g.get("settings") or {}).get("source") == "altron_chat":
            return g
    if flows:
        return flows_engine.get_flow(settings, flows[0]["id"])
    return None


def execute_confirmed_run(settings, flow_id: str) -> str:
    flow = flows_engine.get_flow(settings, flow_id)
    if not flow:
        return "Flow not found for confirmed run."
    issues = validate_plan_or_flow(settings, flow)
    if issues:
        return "Cannot run — validation failed:\n- " + "\n- ".join(issues)
    flows_risk.annotate_flow(flow)
    run = flows_agent.run_autonomous(settings, flow_id)
    ctx = flows_context.build_context(settings, user_command="confirmed_run", flow=flow, run=run)
    flows_context.persist_context(settings, flow_id, ctx)
    _log_trace(
        settings,
        {"phase": "confirm_run_autonomous", "flow_id": flow_id, "ok": run.get("ok"), "phase3": run.get("phase3")},
    )
    return summarize_run(run)
