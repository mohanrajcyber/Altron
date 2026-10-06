from __future__ import annotations

"""ALTRON Flows — production execution engine + persistence.

Honest scope:
- Real graph execution with branch edges (yes/no)
- Variable context + template interpolation
- Trusted-root file ops + ALTRON AI nodes
- Run history persisted under data/flows/runs/
- Schedule / File Created / Webhook / App Started via flows_runtime
"""

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from altron.adapters import checkpoint_store, computer, flows_catalog, flows_expr, pc_roots

FLOW_VERSION = 1
_active_runs: dict[str, threading.Event] = {}
_active_meta: dict[str, dict] = {}


def list_active_runs(settings=None) -> list[dict]:
    """Mission Control: currently executing flow runs (in-memory)."""
    out: list[dict] = []
    now = time.time()
    for run_id, meta in list(_active_meta.items()):
        if run_id not in _active_runs:
            continue
        started = float(meta.get("started") or now)
        total = int(meta.get("total_nodes") or 0)
        done = int(meta.get("completed_nodes") or 0)
        progress = int(round(100.0 * done / total)) if total else None
        out.append(
            {
                "run_id": run_id,
                "flow_id": meta.get("flow_id"),
                "flow_name": meta.get("flow_name"),
                "started": started,
                "elapsed_sec": int(max(0, now - started)),
                "completed_nodes": done,
                "total_nodes": total,
                "current_label": meta.get("current_label") or "",
                "message": meta.get("message") or "Running",
                "node_types": list(meta.get("node_types") or []),
                "progress": progress,
            }
        )
    return out


def _dir(settings) -> Path:
    p = Path(settings.altron_data_dir) / "flows"
    p.mkdir(parents=True, exist_ok=True)
    (p / "runs").mkdir(parents=True, exist_ok=True)
    return p


def catalog() -> list[dict]:
    return flows_catalog.catalog()


def catalog_categories() -> dict[str, list[dict]]:
    return flows_catalog.catalog_by_category()


def open_flows_ui(settings) -> str:
    url = f"http://{settings.altron_host}:{settings.altron_port}/flows"
    try:
        computer.open_url(url)
    except Exception:
        pass
    return f"ALTRON Flows opened.\nURL: {url}"


def status(settings) -> dict:
    roots = pc_roots.list_roots(settings)
    return {
        "ok": True,
        "mode": "local",
        "version": FLOW_VERSION,
        "trusted_roots": len(roots),
        "flows": len(list_flows(settings)),
    }


def list_flows(settings) -> list[dict]:
    ensure_demo(settings)
    out: list[dict] = []
    for path in sorted(_dir(settings).glob("*.json")):
        if path.name == "roots.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "id": data.get("id") or path.stem,
                "name": data.get("name") or path.stem,
                "updated": data.get("updated") or 0,
                "node_count": len(data.get("nodes") or []),
                "version": data.get("version") or 1,
            }
        )
    return out


def get_flow(settings, flow_id: str) -> dict | None:
    path = _dir(settings) / f"{_safe_id(flow_id)}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return normalize_flow(raw)


def save_flow(settings, flow: dict) -> dict:
    data = normalize_flow({**flow, "updated": time.time()})
    fid = _safe_id(str(data.get("id") or uuid.uuid4().hex[:10]))
    data["id"] = fid
    path = _dir(settings) / f"{fid}.json"
    # Phase-2 versioning: snapshot previous revision before overwrite
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            _snapshot_version(settings, prev, reason="pre_save")
        except (OSError, json.JSONDecodeError):
            pass
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _versions_dir(settings, flow_id: str) -> Path:
    p = _dir(settings) / "versions" / _safe_id(flow_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshot_version(settings, flow: dict, reason: str = "edit") -> str:
    fid = _safe_id(str(flow.get("id") or "unknown"))
    vid = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    payload = {
        "version_id": vid,
        "reason": reason,
        "saved_at": time.time(),
        "flow": flow,
    }
    path = _versions_dir(settings, fid) / f"{vid}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # prune to last 40
    files = sorted(_versions_dir(settings, fid).glob("*.json"), key=lambda p: p.name)
    for old in files[:-40]:
        try:
            old.unlink()
        except OSError:
            pass
    return vid


def list_versions(settings, flow_id: str) -> list[dict]:
    out = []
    for path in sorted(_versions_dir(settings, flow_id).glob("*.json"), key=lambda p: p.name, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        flow = data.get("flow") or {}
        out.append(
            {
                "version_id": data.get("version_id") or path.stem,
                "reason": data.get("reason"),
                "saved_at": data.get("saved_at"),
                "name": flow.get("name"),
                "node_count": len(flow.get("nodes") or []),
            }
        )
    return out


def restore_version(settings, flow_id: str, version_id: str) -> dict | None:
    path = _versions_dir(settings, flow_id) / f"{_safe_id(version_id)}.json"
    # version filenames are not safe_id only — try exact then stem match
    if not path.is_file():
        matches = list(_versions_dir(settings, flow_id).glob(f"{version_id}*.json"))
        if not matches:
            matches = [p for p in _versions_dir(settings, flow_id).glob("*.json") if version_id in p.stem]
        if not matches:
            return None
        path = matches[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    flow = data.get("flow")
    if not isinstance(flow, dict):
        return None
    # snapshot current before restore
    current = get_flow(settings, flow_id)
    if current:
        _snapshot_version(settings, current, reason="pre_restore")
    flow["id"] = flow_id
    return save_flow(settings, flow)


def undo_flow(settings, flow_id: str) -> dict | None:
    """Restore the most recent snapshot (previous save)."""
    versions = list_versions(settings, flow_id)
    if not versions:
        return None
    return restore_version(settings, flow_id, str(versions[0]["version_id"]))


def duplicate_flow(settings, flow_id: str) -> dict | None:
    flow = get_flow(settings, flow_id)
    if not flow:
        return None
    copy = json.loads(json.dumps(flow))
    copy["id"] = "flow_" + uuid.uuid4().hex[:8]
    copy["name"] = (flow.get("name") or "Flow") + " (copy)"
    settings_meta = copy.get("settings") if isinstance(copy.get("settings"), dict) else {}
    settings_meta = {**settings_meta, "duplicated_from": flow_id}
    copy["settings"] = settings_meta
    return save_flow(settings, copy)


def delete_flow(settings, flow_id: str) -> str:
    path = _dir(settings) / f"{_safe_id(flow_id)}.json"
    if not path.is_file():
        return "Flow not found"
    path.unlink()
    return f"Deleted flow {flow_id}"


def normalize_flow(raw: dict) -> dict:
    """Migrate legacy flows (x/y, from/to edges) to v1 schema."""
    nodes_in = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    edges_in = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    nodes: list[dict] = []
    seen: set[str] = set()
    for n in nodes_in:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        nid = str(n["id"])
        if nid in seen:
            continue
        seen.add(nid)
        pos = n.get("position") if isinstance(n.get("position"), dict) else {}
        x = pos.get("x", n.get("x", 0))
        y = pos.get("y", n.get("y", 0))
        ntype = flows_catalog.TYPE_ALIASES.get(str(n.get("type") or ""), str(n.get("type") or "trigger.manual"))
        meta = flows_catalog.meta_for(ntype) or {}
        nodes.append(
            {
                "id": nid,
                "type": ntype,
                "label": n.get("label") or meta.get("label") or ntype,
                "description": n.get("description") or meta.get("desc") or "",
                "position": {"x": float(x), "y": float(y)},
                "config": n.get("config") if isinstance(n.get("config"), dict) else {},
                "disabled": bool(n.get("disabled")),
            }
        )
    edges: list[dict] = []
    for i, e in enumerate(edges_in):
        if not isinstance(e, dict):
            continue
        src = e.get("source") or e.get("from")
        tgt = e.get("target") or e.get("to")
        if not src or not tgt:
            continue
        edges.append(
            {
                "id": e.get("id") or f"e{i}",
                "source": src,
                "target": tgt,
                "sourceHandle": e.get("sourceHandle") or e.get("label") or "default",
                "targetHandle": e.get("targetHandle") or "in",
                "label": e.get("label") or "",
            }
        )
    return {
        "version": FLOW_VERSION,
        "id": raw.get("id") or "",
        "name": str(raw.get("name") or "Untitled flow")[:120],
        "nodes": nodes,
        "edges": edges,
        "variables": raw.get("variables") if isinstance(raw.get("variables"), dict) else {},
        "permissions": raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {},
        "settings": raw.get("settings") if isinstance(raw.get("settings"), dict) else {},
        "updated": raw.get("updated") or time.time(),
    }


def _root_path(settings, *names: str) -> str:
    roots = pc_roots.list_roots(settings)
    for name in names:
        for r in roots:
            if r["name"].lower() == name.lower() or str(r["path"]).lower().endswith(f"\\{name.lower()}"):
                return r["path"]
    return roots[0]["path"] if roots else ""


def _ensure_flow(settings, flow_id: str, flow: dict) -> None:
    path = _dir(settings) / f"{_safe_id(flow_id)}.json"
    if path.is_file():
        return
    save_flow(settings, {**flow, "id": flow_id})


def ensure_demo(settings) -> None:
    desktop = _root_path(settings, "Desktop")
    downloads = _root_path(settings, "Downloads")
    documents = _root_path(settings, "Documents")
    _ensure_flow(
        settings,
        "demo_desktop_scan",
        {
            "name": "Demo · Scan Desktop",
            "nodes": [
                {"id": "n1", "type": "trigger.manual", "label": "Manual Trigger", "position": {"x": 120, "y": 200}, "config": {}},
                {"id": "n2", "type": "files.list", "label": "List Desktop", "position": {"x": 420, "y": 200}, "config": {"path": desktop}},
                {"id": "n3", "type": "logic.log", "label": "Log result", "position": {"x": 720, "y": 200}, "config": {"message": ""}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
            ],
        },
    )
    _ensure_flow(
        settings,
        "pdf_auto_organizer",
        {
            "name": "PDF Auto Organizer",
            "nodes": [
                {"id": "n1", "type": "trigger.manual", "label": "Manual Trigger", "description": "Run now (Schedule in Phase 5)", "position": {"x": 60, "y": 180}, "config": {}},
                {"id": "n2", "type": "files.list", "label": "List Downloads", "description": "Scan Downloads for PDFs", "position": {"x": 300, "y": 180}, "config": {"path": downloads}},
                {"id": "n3", "type": "logic.if", "label": "If / Else", "description": "Is file a PDF?", "position": {"x": 540, "y": 180}, "config": {"condition": "pdf"}},
                {"id": "n4", "type": "ai.agent", "label": "AI Agent", "description": "Analyze PDF and extract information", "position": {"x": 780, "y": 80}, "config": {
                    "prompt": "Analyze the PDF. Return: Title, Summary, Key points, Category.",
                    "input_var": "{{$variables.file.text}}",
                    "output_var": "ai.result",
                }},
                {"id": "n5", "type": "files.move", "label": "Move File", "description": "Move to Documents/Reports", "position": {"x": 1020, "y": 80}, "config": {"src": "{{$file.path}}", "dst_dir": documents}},
                {"id": "n6", "type": "logic.log", "label": "Log", "description": "Write execution log", "position": {"x": 1260, "y": 80}, "config": {"message": "PDF organized: {{$file.name}}"}},
                {"id": "n7", "type": "notify.log", "label": "Notification", "description": "Not a PDF (skipped)", "position": {"x": 780, "y": 300}, "config": {"message": "Skipped non-PDF file"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "yes", "targetHandle": "in", "label": "Yes"},
                {"id": "e4", "source": "n4", "target": "n5", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e5", "source": "n5", "target": "n6", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e6", "source": "n3", "target": "n7", "sourceHandle": "no", "targetHandle": "in", "label": "No"},
            ],
        },
    )
    _ensure_flow(
        settings,
        "demo_filter_ai",
        {
            "name": "Demo · Filter → AI → Log",
            "nodes": [
                {"id": "n1", "type": "trigger.manual", "label": "Manual Trigger", "position": {"x": 80, "y": 180}, "config": {}},
                {"id": "n2", "type": "files.list", "label": "List Desktop", "position": {"x": 320, "y": 180}, "config": {"path": desktop}},
                {"id": "n3", "type": "logic.filter", "label": "Filter", "position": {"x": 560, "y": 180}, "config": {"pattern": "."}},
                {
                    "id": "n4",
                    "type": "ai.agent",
                    "label": "AI Agent",
                    "position": {"x": 800, "y": 180},
                    "config": {
                        "prompt": "From this desktop file list, name 3 notable items and one short observation. Be concise.",
                        "input_var": "",
                        "output_var": "ai.result",
                    },
                },
                {"id": "n5", "type": "logic.log", "label": "Log", "position": {"x": 1040, "y": 180}, "config": {"message": ""}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e4", "source": "n4", "target": "n5", "sourceHandle": "default", "targetHandle": "in"},
            ],
        },
    )
    _ensure_flow(
        settings,
        "demo_if_branch",
        {
            "name": "Demo · If / Else Branch",
            "nodes": [
                {"id": "n1", "type": "trigger.manual", "label": "Manual Trigger", "position": {"x": 80, "y": 200}, "config": {}},
                {"id": "n2", "type": "files.list", "label": "List Desktop", "position": {"x": 320, "y": 200}, "config": {"path": desktop}},
                {
                    "id": "n3",
                    "type": "logic.if",
                    "label": "If / Else",
                    "position": {"x": 560, "y": 200},
                    "config": {"condition": "count > 0"},
                },
                {"id": "n4", "type": "logic.log", "label": "YES Log", "position": {"x": 820, "y": 120}, "config": {"message": "YES branch: Desktop has entries"}},
                {"id": "n5", "type": "logic.log", "label": "NO Log", "position": {"x": 820, "y": 300}, "config": {"message": "NO branch: Desktop empty"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
                {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "yes", "targetHandle": "in", "label": "Yes"},
                {"id": "e4", "source": "n3", "target": "n5", "sourceHandle": "no", "targetHandle": "in", "label": "No"},
            ],
        },
    )


def stop_run(run_id: str) -> dict:
    ev = _active_runs.get(run_id)
    if ev:
        ev.set()
        return {"ok": True, "message": f"Stop requested for {run_id}"}
    return {"ok": False, "message": "Run not active"}


def test_node(settings, node: dict, context: dict | None = None) -> dict:
    ctx = _new_context(context)
    ntype = flows_catalog.TYPE_ALIASES.get(str(node.get("type") or ""), str(node.get("type") or ""))
    if not flows_catalog.is_implemented(ntype):
        return {"ok": False, "error": f"NOT IMPLEMENTED: {ntype}", "ms": 0}
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    t0 = time.time()
    try:
        out = _normalize_output(_exec_node(settings, ntype, cfg, ctx, logs=[]))
        _store_node_result(ctx, node, "SUCCESS", cfg, out)
        return {
            "ok": True,
            "output": out.get("message"),
            "data": out.get("data"),
            "ms": int((time.time() - t0) * 1000),
            "variables": ctx.get("variables") or {},
            "nodes": ctx.get("nodes") or {},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "ms": int((time.time() - t0) * 1000)}


def run_flow(settings, flow_id: str, on_event=None) -> dict[str, Any]:
    """Execute a flow. Optional on_event(dict) emits live progress for SSE clients."""

    def emit(event: dict) -> None:
        if on_event:
            try:
                on_event(event)
            except Exception:  # noqa: BLE001
                pass

    flow = get_flow(settings, flow_id)
    if not flow:
        err = {"ok": False, "status": "FAILED", "message": "Flow not found", "logs": [], "nodeResults": []}
        emit({"type": "error", **err})
        return err

    run_id = uuid.uuid4().hex[:12]
    stop_ev = threading.Event()
    _active_runs[run_id] = stop_ev
    _active_meta[run_id] = {
        "flow_id": flow.get("id"),
        "flow_name": flow.get("name"),
        "started": time.time(),
        "completed_nodes": 0,
        "total_nodes": len([n for n in (flow.get("nodes") or []) if not n.get("disabled")]),
        "current_label": "",
        "message": "FLOW STARTED",
        "node_types": [n.get("type") for n in (flow.get("nodes") or [])],
    }

    checkpoint_store.start_run(settings, run_id, str(flow.get("id") or ""), str(flow.get("name") or ""), _active_meta[run_id]["total_nodes"])

    nodes = {n["id"]: n for n in flow.get("nodes") or []}
    edges = flow.get("edges") or []
    ctx = _new_context()
    ctx["_flow_id"] = flow.get("id")
    logs: list[dict] = []
    node_results: list[dict] = []
    started = time.time()
    executed: set[str] = set()
    order = 0

    def log(msg: str, node_id: str = "", level: str = "info") -> None:
        entry = {"t": time.time(), "level": level, "node_id": node_id, "message": msg}
        logs.append(entry)
        emit({"type": "log", **entry})

    log("FLOW STARTED", level="info")
    emit({"type": "flow_start", "runId": run_id, "flowId": flow.get("id"), "flowName": flow.get("name")})
    for n in nodes.values():
        if not n.get("disabled"):
            emit({"type": "node_state", "nodeId": n["id"], "status": "QUEUED", "order": None})

    status = "RUNNING"
    ok = True
    active_edge = ""

    triggers = [n for n in nodes.values() if str(n.get("type", "")).startswith("trigger.") and not n.get("disabled")]
    if not triggers:
        triggers = [n for n in nodes.values() if not n.get("disabled")][:1]
    queue: list[str] = [t["id"] for t in triggers]

    while queue:
        if stop_ev.is_set():
            status = "CANCELLED"
            log("Flow cancelled by user", level="warn")
            ok = False
            break
        nid = queue.pop(0)
        node = nodes.get(nid)
        if not node or node.get("disabled"):
            continue
        ntype = flows_catalog.TYPE_ALIASES.get(str(node.get("type") or ""), str(node.get("type") or ""))
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        label = node.get("label") or ntype
        order += 1
        t0 = time.time()
        emit({"type": "node_state", "nodeId": nid, "status": "RUNNING", "order": order, "activeEdge": active_edge})
        log(f"{label} started", node_id=nid)
        if run_id in _active_meta:
            _active_meta[run_id]["current_label"] = label
            _active_meta[run_id]["message"] = f"Running {label}"
            checkpoint_store.update_run(settings, run_id, int(_active_meta[run_id].get("completed_nodes") or 0), label)
        try:
            raw_out = _exec_node(settings, ntype, cfg, ctx, logs=logs, node_id=nid)
            out = _normalize_output(raw_out)
            ms = int((time.time() - t0) * 1000)
            log(f"{label} SUCCESS ({ms}ms) — {out.get('message')}", node_id=nid)
            _store_node_result(ctx, node, "SUCCESS", dict(cfg), out)
            result = {
                "nodeId": nid,
                "type": ntype,
                "label": label,
                "status": "SUCCESS",
                "startTime": t0,
                "endTime": time.time(),
                "ms": ms,
                "order": order,
                "input": dict(cfg),
                "output": out.get("data"),
                "message": out.get("message"),
                "error": None,
            }
            node_results.append(result)
            executed.add(nid)
            if run_id in _active_meta:
                _active_meta[run_id]["completed_nodes"] = int(_active_meta[run_id].get("completed_nodes") or 0) + 1
            emit(
                {
                    "type": "node_state",
                    "nodeId": nid,
                    "status": "SUCCESS",
                    "order": order,
                    "ms": ms,
                    "output": out.get("message"),
                    "data": out.get("data"),
                    "input": dict(cfg),
                }
            )
            if ntype == "logic.foreach":
                items = list(ctx.get("foreach_items") or [])
                body_roots = _next_nodes(nid, edges, ntype, out, ctx)
                # ForEach owns its body — do not also enqueue roots outside the loop here.
                body_ids = _collect_descendants(body_roots, edges)
                loop_results: list[Any] = []
                success_n = 0
                failed_n = 0
                for idx, item in enumerate(items):
                    if stop_ev.is_set():
                        status = "CANCELLED"
                        log("Flow cancelled during ForEach", level="warn")
                        ok = False
                        break
                    ctx["item"] = item
                    if isinstance(item, dict):
                        ctx["file"] = {
                            "path": item.get("path") or "",
                            "name": item.get("name") or "",
                            "extension": str(Path(str(item.get("name") or "")).suffix).lstrip("."),
                        }
                    ctx["loop"] = {"index": idx, "total": len(items), "item": item}
                    ctx.setdefault("variables", {})["loop.index"] = idx
                    ctx.setdefault("variables", {})["loop.total"] = len(items)
                    ctx.setdefault("variables", {})["item.name"] = (item or {}).get("name") if isinstance(item, dict) else str(item)
                    ctx.setdefault("variables", {})["item.path"] = (item or {}).get("path") if isinstance(item, dict) else ""
                    log(f"ForEach item {idx + 1}/{len(items)}: {(item or {}).get('name') if isinstance(item, dict) else item}", node_id=nid)
                    emit({"type": "edge_active", "edgeId": "", "source": nid, "target": body_roots[0] if body_roots else ""})
                    emit(
                        {
                            "type": "foreach_progress",
                            "nodeId": nid,
                            "index": idx,
                            "total": len(items),
                            "item": item,
                        }
                    )
                    sub_ok, order = _run_subgraph(
                        settings,
                        nodes,
                        edges,
                        body_roots,
                        body_ids,
                        ctx,
                        logs,
                        node_results,
                        stop_ev,
                        emit,
                        order,
                        on_event=on_event,
                    )
                    loop_results.append({"index": idx, "item": item, "ok": sub_ok})
                    if sub_ok:
                        success_n += 1
                    else:
                        failed_n += 1
                        ok = False
                        status = "FAILED"
                        log(f"ForEach item {idx + 1} failed — continuing remaining items", node_id=nid, level="warn")
                        # Phase-2 batch: do not abort remaining iterations
                        continue
                metrics = {
                    "total": len(items),
                    "success": success_n,
                    "failed": failed_n,
                    "skipped": max(0, len(items) - success_n - failed_n),
                    "results": loop_results,
                }
                ctx.setdefault("variables", {})["foreach.count"] = len(items)
                ctx.setdefault("variables", {})["foreach.success"] = success_n
                ctx.setdefault("variables", {})["foreach.failed"] = failed_n
                ctx["foreach_metrics"] = metrics
                ctx["last_output"] = metrics
                # attach metrics onto foreach node result
                if node_results:
                    for r in reversed(node_results):
                        if r.get("nodeId") == nid:
                            r["foreach"] = metrics
                            break
                executed.update(body_ids)
                if on_event:
                    time.sleep(0.05)
                if not ok:
                    break
                continue

            next_ids = _next_nodes(nid, edges, ntype, out, ctx)
            for nxt in next_ids:
                edge = next((e for e in edges if e.get("source") == nid and e.get("target") == nxt), None)
                active_edge = (edge or {}).get("id") or ""
                emit({"type": "edge_active", "edgeId": active_edge, "source": nid, "target": nxt})
            queue.extend(next_ids)
            if on_event:
                time.sleep(0.12)  # brief pace so UI can paint RUNNING→SUCCESS
        except Exception as exc:  # noqa: BLE001
            ms = int((time.time() - t0) * 1000)
            err = str(exc)
            log(f"{label} FAILED: {err}", node_id=nid, level="error")
            empty = {"message": "", "data": {}}
            _store_node_result(ctx, node, "FAILED", dict(cfg), empty, error=err)
            result = {
                "nodeId": nid,
                "type": ntype,
                "label": label,
                "status": "FAILED",
                "startTime": t0,
                "endTime": time.time(),
                "ms": ms,
                "order": order,
                "input": dict(cfg),
                "output": {},
                "message": "",
                "error": err,
            }
            node_results.append(result)
            executed.add(nid)
            emit({"type": "node_state", "nodeId": nid, "status": "FAILED", "order": order, "error": err, "ms": ms, "input": dict(cfg)})
            status = "FAILED"
            ok = False
            break

    if ok and status == "RUNNING":
        status = "SUCCESS"
        log("FLOW COMPLETED")

    for nid, node in nodes.items():
        if nid not in executed and not node.get("disabled"):
            emit({"type": "node_state", "nodeId": nid, "status": "SKIPPED", "order": None})
            ntype = flows_catalog.TYPE_ALIASES.get(str(node.get("type") or ""), str(node.get("type") or ""))
            label = node.get("label") or ntype
            node_results.append(
                {
                    "nodeId": nid,
                    "type": ntype,
                    "label": label,
                    "status": "SKIPPED",
                    "startTime": None,
                    "endTime": None,
                    "ms": 0,
                    "order": None,
                    "input": {},
                    "output": {},
                    "message": "Skipped (branch not taken or unreachable)",
                    "error": None,
                }
            )
            log(f"{label} SKIPPED", node_id=nid, level="info")

    ended = time.time()
    # Persist a clean nodes map (by id only) for run history / inspector
    nodes_snapshot = {
        nid: ctx["nodes"][nid]
        for nid in nodes
        if nid in (ctx.get("nodes") or {})
    }
    run = {
        "id": run_id,
        "flow_id": flow.get("id"),
        "flow_name": flow.get("name"),
        "ok": ok,
        "status": status,
        "started": started,
        "ended": ended,
        "duration_ms": int((ended - started) * 1000),
        "logs": logs,
        "nodeResults": node_results,
        "variables": ctx.get("variables") or {},
        "foreach": ctx.get("foreach_metrics"),
        "nodes": nodes_snapshot,
        "steps": [
            {
                "node_id": r["nodeId"],
                "type": r["type"],
                "label": r["label"],
                "ok": r["status"] == "SUCCESS",
                "ms": r["ms"],
                "output": r.get("message") or r.get("error") or "",
                "data": r.get("output"),
                "status": r["status"],
                "order": r.get("order"),
            }
            for r in node_results
        ],
    }
    (_dir(settings) / "runs" / f"{run_id}.json").write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    checkpoint_store.finish_run(settings, run_id, status)
    _active_runs.pop(run_id, None)
    emit(
        {
            "type": "flow_done",
            "id": run["id"],
            "ok": run["ok"],
            "status": run["status"],
            "duration_ms": run["duration_ms"],
            "variables": run["variables"],
            "nodes": nodes_snapshot,
        }
    )
    return run


def run_flow_events(settings, flow_id: str):
    """Yield SSE-ready dict events while executing."""
    queue: list[dict] = []

    def on_event(ev: dict) -> None:
        queue.append(ev)

    result_holder: dict[str, Any] = {}

    def worker() -> None:
        result_holder["run"] = run_flow(settings, flow_id, on_event=on_event)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while t.is_alive() or queue:
        while queue:
            yield queue.pop(0)
        time.sleep(0.02)
    if "run" in result_holder:
        yield {"type": "run_complete", "run": result_holder["run"]}


def recent_runs(settings, limit: int = 20) -> list[dict]:
    runs_dir = _dir(settings) / "runs"
    files = sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "id": data.get("id"),
                "flow_id": data.get("flow_id"),
                "flow_name": data.get("flow_name"),
                "ok": data.get("ok"),
                "status": data.get("status"),
                "started": data.get("started"),
                "ended": data.get("ended"),
                "duration_ms": data.get("duration_ms"),
                "steps": len(data.get("nodeResults") or data.get("steps") or []),
            }
        )
    return out


def get_run(settings, run_id: str) -> dict | None:
    path = _dir(settings) / "runs" / f"{_safe_id(run_id)}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_id(fid: str) -> str:
    return "".join(c for c in fid if c.isalnum() or c in {"_", "-"})[:64] or "flow"


def _new_context(partial: dict | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trigger": {},
        "nodes": {},
        "variables": {},
        "file": {},
        "last_path": "",
        "last_listing": [],
        "last_output": None,
        "last_node_id": "",
    }
    if partial:
        for k, v in partial.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update(v)
            else:
                base[k] = v
    return base


def _node_key(label: str, nid: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "", str(label or ""))
    return clean or nid


def _stringify(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, ensure_ascii=False, indent=2)
        except TypeError:
            return str(val)
    return str(val)


def _lookup_path(ctx: dict, parts: list[str]) -> Any:
    """Resolve dotted path; supports composite keys like variables['ai.result'].suggested_name."""
    if not parts:
        return ""
    cur: Any = ctx
    i = 0
    while i < len(parts):
        if not isinstance(cur, dict):
            if isinstance(cur, list) and parts[i].isdigit():
                idx = int(parts[i])
                cur = cur[idx] if 0 <= idx < len(cur) else ""
                i += 1
                continue
            return ""
        # longest dotted key match first (ai.result before ai)
        matched = False
        lower = {str(k).lower(): k for k in cur.keys()}
        for j in range(len(parts), i, -1):
            key = ".".join(parts[i:j])
            if key in cur:
                cur = cur[key]
                i = j
                matched = True
                break
            if key.lower() in lower:
                cur = cur[lower[key.lower()]]
                i = j
                matched = True
                break
        if not matched:
            return ""
    return cur


def _resolve_template(text: str, ctx: dict) -> str:
    if not text:
        return ""

    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        if key.startswith("$"):
            key = key[1:]
        parts = [p for p in key.split(".") if p]
        if not parts:
            return ""
        # support nodes.<id|Label>.output...
        val = _lookup_path(ctx, parts)
        return _stringify(val)

    return re.sub(r"\{\{([^}]+)\}\}", repl, text)


def _normalize_output(raw: Any) -> dict[str, Any]:
    """Every node returns {message, data}."""
    if isinstance(raw, dict) and ("message" in raw or "data" in raw):
        return {
            "message": str(raw.get("message") or ""),
            "data": raw.get("data") if raw.get("data") is not None else raw,
        }
    if isinstance(raw, dict):
        return {"message": _stringify(raw)[:400], "data": raw}
    return {"message": str(raw), "data": {"value": raw}}


def _store_node_result(ctx: dict, node: dict, status: str, input_data: dict, output: dict, error: str | None = None) -> None:
    nid = node["id"]
    label = node.get("label") or nid
    alias = _node_key(label, nid)
    payload = {
        "id": nid,
        "label": label,
        "status": status,
        "input": input_data,
        "output": output.get("data"),
        "message": output.get("message") or "",
        "error": error,
    }
    ctx.setdefault("nodes", {})[nid] = payload
    ctx["nodes"][alias] = payload
    ctx["last_output"] = output.get("data")
    ctx["last_node_id"] = nid
    ctx.setdefault("variables", {})[f"{alias}.output"] = output.get("data")
    ctx.setdefault("variables", {})[f"{alias}.message"] = output.get("message")
    ctx.setdefault("variables", {})["last.output"] = output.get("data")
    ctx.setdefault("variables", {})["last.message"] = output.get("message")


def _next_nodes(nid: str, edges: list, ntype: str, output: Any, ctx: dict) -> list[str]:
    out: list[str] = []
    for e in edges:
        if e.get("source") != nid:
            continue
        handle = (e.get("sourceHandle") or "default").lower()
        if ntype == "logic.if":
            branch = "yes" if ctx.get("variables", {}).get("_last_if") else "no"
            # only the matching Yes/No handle — never both
            if handle != branch:
                continue
        out.append(str(e.get("target")))
    return out


def _collect_descendants(roots: list[str], edges: list) -> set[str]:
    seen: set[str] = set()
    q = list(roots)
    while q:
        cur = q.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        for e in edges:
            if e.get("source") == cur:
                tgt = str(e.get("target"))
                if tgt not in seen:
                    q.append(tgt)
    return seen


def _run_subgraph(
    settings,
    nodes: dict,
    edges: list,
    start_ids: list[str],
    body_ids: set[str],
    ctx: dict,
    logs: list,
    node_results: list,
    stop_ev,
    emit,
    order: int,
    on_event=None,
) -> tuple[bool, int]:
    """Execute foreach body once. Returns (ok, updated_order)."""
    queue = list(start_ids)
    ok = True

    def log(msg: str, node_id: str = "", level: str = "info") -> None:
        entry = {"t": time.time(), "level": level, "node_id": node_id, "message": msg}
        logs.append(entry)
        emit({"type": "log", **entry})

    while queue:
        if stop_ev.is_set():
            return False, order
        nid = queue.pop(0)
        if nid not in body_ids:
            continue
        node = nodes.get(nid)
        if not node or node.get("disabled"):
            continue
        ntype = flows_catalog.TYPE_ALIASES.get(str(node.get("type") or ""), str(node.get("type") or ""))
        if ntype == "logic.foreach":
            continue  # nested foreach not supported in Phase 1 body
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        label = node.get("label") or ntype
        order += 1
        t0 = time.time()
        emit({"type": "node_state", "nodeId": nid, "status": "RUNNING", "order": order})
        log(f"{label} started", node_id=nid)
        try:
            raw_out = _exec_node(settings, ntype, cfg, ctx, logs=logs, node_id=nid)
            out = _normalize_output(raw_out)
            ms = int((time.time() - t0) * 1000)
            log(f"{label} SUCCESS ({ms}ms) — {out.get('message')}", node_id=nid)
            _store_node_result(ctx, node, "SUCCESS", dict(cfg), out)
            node_results.append(
                {
                    "nodeId": nid,
                    "type": ntype,
                    "label": label,
                    "status": "SUCCESS",
                    "startTime": t0,
                    "endTime": time.time(),
                    "ms": ms,
                    "order": order,
                    "input": dict(cfg),
                    "output": out.get("data"),
                    "message": out.get("message"),
                    "error": None,
                    "loop_index": (ctx.get("loop") or {}).get("index"),
                }
            )
            emit(
                {
                    "type": "node_state",
                    "nodeId": nid,
                    "status": "SUCCESS",
                    "order": order,
                    "ms": ms,
                    "output": out.get("message"),
                    "data": out.get("data"),
                }
            )
            next_ids = [t for t in _next_nodes(nid, edges, ntype, out, ctx) if t in body_ids]
            queue.extend(next_ids)
            if on_event:
                time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            ms = int((time.time() - t0) * 1000)
            err = str(exc)
            log(f"{label} FAILED: {err}", node_id=nid, level="error")
            empty = {"message": "", "data": {}}
            _store_node_result(ctx, node, "FAILED", dict(cfg), empty, error=err)
            node_results.append(
                {
                    "nodeId": nid,
                    "type": ntype,
                    "label": label,
                    "status": "FAILED",
                    "ms": ms,
                    "order": order,
                    "error": err,
                    "loop_index": (ctx.get("loop") or {}).get("index"),
                }
            )
            emit({"type": "node_state", "nodeId": nid, "status": "FAILED", "order": order, "error": err})
            return False, order
    return ok, order


def _exec_node(
    settings,
    ntype: str,
    cfg: dict,
    ctx: dict,
    logs: list | None = None,
    node_id: str = "",
) -> dict[str, Any]:
    cfg = {k: _resolve_template(str(v), ctx) for k, v in cfg.items()}

    if ntype.startswith("trigger."):
        # Phase-1 triggers are implemented; background firing via flows_runtime.
        from altron.adapters import flows_runtime

        stash = flows_runtime.take_trigger_stash(str(ctx.get("_flow_id") or "")) or {}
        data = {
            "source": ntype,
            "at": time.time(),
            "note": cfg.get("note") or cfg.get("cron") or cfg.get("path") or "",
            **{k: v for k, v in stash.items() if k != "source"},
        }
        if stash.get("source"):
            data["source"] = stash.get("source")
        ctx["trigger"] = data
        # expose file info for file_created
        if data.get("path"):
            p = Path(str(data["path"]))
            ctx["file"] = {"path": str(p), "name": p.name, "extension": p.suffix.lstrip(".")}
            ctx["last_path"] = str(p)
        return {"message": f"Triggered ({data.get('source')})", "data": data}

    if ntype == "logic.log" or ntype == "notify.log":
        msg = (cfg.get("message") or "").strip()
        prev = ctx.get("last_output")
        if not msg:
            if isinstance(prev, dict) and "file_count" in prev:
                msg = f"Previous node returned {prev.get('file_count', 0)} files ({prev.get('count', 0)} entries) from {prev.get('folder') or prev.get('path')}"
            elif isinstance(prev, dict) and prev.get("text"):
                msg = f"AI/text output ({len(str(prev.get('text')))} chars):\n{str(prev.get('text'))[:800]}"
            elif isinstance(prev, dict) and "logged" in prev:
                msg = str(prev.get("logged"))
            elif isinstance(prev, dict) and "branch" in prev:
                msg = f"Branch = {prev.get('branch')} (result={prev.get('result')})"
            elif prev is not None:
                msg = f"Previous output:\n{_stringify(prev)[:1500]}"
            else:
                msg = "Log (no previous output)"
        else:
            msg = _resolve_template(msg, ctx) if "{{" in msg else msg
        data = {"logged": msg, "from": prev}
        return {"message": msg, "data": data}

    if ntype == "logic.delay":
        try:
            sec = max(0, min(30, int(float(cfg.get("seconds") or "1"))))
        except ValueError as exc:
            raise RuntimeError("Delay seconds must be a number") from exc
        time.sleep(sec)
        return {"message": f"Delayed {sec}s", "data": {"seconds": sec}}

    if ntype == "logic.filter":
        pattern = (cfg.get("pattern") or "").strip().lower().replace("*", "")
        listing = list(ctx.get("last_listing") or [])
        if not listing and isinstance(ctx.get("last_output"), dict):
            listing = list(ctx["last_output"].get("entries") or ctx["last_output"].get("files") or [])
        if pattern:
            filtered = [e for e in listing if pattern in str(e.get("name", "")).lower()]
        else:
            filtered = listing
        ctx["last_listing"] = filtered
        files = [e for e in filtered if e.get("type") == "file"]
        ctx.setdefault("variables", {})["filter.count"] = len(filtered)
        ctx.setdefault("variables", {})["filter.file_count"] = len(files)
        data = {
            "pattern": pattern,
            "count": len(filtered),
            "file_count": len(files),
            "entries": filtered,
            "files": files,
        }
        return {"message": f"Filtered to {len(files)} files / {len(filtered)} entries (pattern={pattern or '*'})", "data": data}

    if ntype == "logic.if":
        cond_raw = (cfg.get("condition") or "").strip()
        result = flows_expr.evaluate_bool(cond_raw, ctx)
        ctx.setdefault("variables", {})["_last_if"] = result
        branch = "yes" if result else "no"
        return {
            "message": f"If → {branch.upper()} ({cond_raw or 'empty'})",
            "data": {"condition": cond_raw, "result": result, "branch": branch},
        }

    if ntype == "logic.foreach":
        # Items collected here; run_flow expands iterations.
        listing = list(ctx.get("last_listing") or [])
        if not listing and isinstance(ctx.get("last_output"), dict):
            listing = list(ctx["last_output"].get("files") or ctx["last_output"].get("entries") or [])
        files = [e for e in listing if e.get("type") == "file"] or listing
        try:
            max_n = max(1, min(50, int(float(cfg.get("max") or "20"))))
        except ValueError:
            max_n = 20
        items = files[:max_n]
        ctx["foreach_items"] = items
        return {
            "message": f"ForEach prepared {len(items)} items",
            "data": {"count": len(items), "items": items},
        }

    if ntype == "files.list":
        path = cfg.get("path") or ctx.get("last_path") or ""
        recursive = str(cfg.get("recursive") or "").strip().lower() in {"1", "true", "yes", "on"}
        pattern = cfg.get("pattern") or ""
        data = pc_roots.list_dir(settings, path, recursive=recursive, pattern=pattern)
        if not data.get("ok"):
            raise RuntimeError(data.get("message") or "list failed")
        ctx["last_path"] = data.get("path") or path
        ctx["last_listing"] = data.get("entries") or []
        ctx.setdefault("variables", {})["list.count"] = data.get("count") or 0
        ctx.setdefault("variables", {})["list.file_count"] = data.get("file_count") or 0
        msg = f"Listed {data.get('folder')}: {data.get('file_count', 0)} files / {data.get('count', 0)} entries"
        return {"message": msg, "data": data}

    if ntype == "files.read":
        path = cfg.get("path") or ctx.get("last_path") or ""
        resolved = pc_roots.resolve_in_roots(settings, path)
        if resolved is None or not resolved.is_file():
            raise RuntimeError(f"Blocked or missing file: {path}")
        file_meta = {"path": str(resolved), "name": resolved.name, "extension": resolved.suffix.lstrip(".")}
        if resolved.suffix.lower() == ".pdf":
            from altron.adapters import flows_pdf

            try:
                extracted = flows_pdf.extract_text(resolved)
            except flows_pdf.PdfExtractError as exc:
                raise RuntimeError(str(exc)) from exc
            text = extracted.get("text") or ""
            ctx["file"] = {**file_meta, "pages": extracted.get("pages"), "pdf": True}
            ctx.setdefault("variables", {})["file.text"] = text[:8000]
            ctx.setdefault("variables", {})["file.pages"] = extracted.get("pages")
            data = {
                **file_meta,
                "text": text[:8000],
                "pages": extracted.get("pages"),
                "chars": extracted.get("chars"),
                "truncated": extracted.get("truncated"),
                "source": "pdf",
            }
            if not text.strip():
                return {
                    "message": f"Read PDF {resolved.name}: no extractable text ({extracted.get('pages')} pages)",
                    "data": data,
                }
            return {"message": f"Read PDF {resolved.name} ({extracted.get('chars')} chars, {extracted.get('pages')} pages)", "data": data}

        text = resolved.read_text(encoding="utf-8", errors="ignore")[:64000]
        ctx["file"] = file_meta
        ctx.setdefault("variables", {})["file.text"] = text[:2000]
        return {"message": f"Read {resolved.name} ({len(text)} chars)", "data": {**file_meta, "text": text[:4000], "source": "text"}}

    if ntype == "files.write":
        path = cfg.get("path") or ""
        content = cfg.get("content") or ""
        resolved = pc_roots.resolve_in_roots(settings, path)
        if resolved is None:
            base = pc_roots.root_paths(settings)[0] if pc_roots.root_paths(settings) else Path.home()
            resolved = (base / path).resolve()
            if pc_roots.resolve_in_roots(settings, str(resolved)) is None:
                raise RuntimeError(f"Blocked write path: {path}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        ctx["last_path"] = str(resolved)
        data = {"path": str(resolved), "bytes": len(content)}
        return {"message": f"Wrote {resolved} ({len(content)} chars)", "data": data}

    if ntype == "files.copy":
        msg = _copy_or_move(settings, cfg, ctx, move=False)
        return {"message": msg, "data": {"path": ctx.get("last_path"), "file": ctx.get("file")}}
    if ntype == "files.move":
        msg = _copy_or_move(settings, cfg, ctx, move=True)
        return {"message": msg, "data": {"path": ctx.get("last_path"), "file": ctx.get("file")}}
    if ntype == "files.rename":
        src = pc_roots.resolve_in_roots(settings, str(cfg.get("src") or ctx.get("last_path") or ""))
        new_name = str(cfg.get("new_name") or "").strip()
        if src is None or not src.is_file():
            raise RuntimeError("Rename source blocked or missing")
        if not new_name or "/" in new_name or "\\" in new_name or new_name in {".", ".."}:
            raise RuntimeError("Invalid new filename")
        # strip path components — name only
        new_name = Path(new_name).name
        dest = src.parent / new_name
        if pc_roots.resolve_in_roots(settings, str(dest)) is None:
            raise RuntimeError("Rename destination blocked")
        if dest.exists() and dest.resolve() != src.resolve():
            raise RuntimeError(f"Target already exists: {dest.name}")
        src.rename(dest)
        ctx["last_path"] = str(dest)
        ctx["file"] = {"path": str(dest), "name": dest.name, "extension": dest.suffix.lstrip(".")}
        if isinstance(ctx.get("item"), dict):
            ctx["item"] = {**ctx["item"], "path": str(dest), "name": dest.name}
        return {"message": f"Renamed → {dest.name}", "data": {"path": str(dest), "file": ctx["file"], "name": dest.name}}

    if ntype == "apps.open_path":
        path = cfg.get("path") or ctx.get("last_path") or ""
        resolved = pc_roots.resolve_in_roots(settings, path)
        if resolved is None:
            raise RuntimeError(f"Blocked path: {path}")
        computer.start_file(str(resolved))
        return {"message": f"Opened {resolved}", "data": {"path": str(resolved)}}

    if ntype == "browser.open_url":
        url = cfg.get("url") or "https://www.google.com"
        msg = computer.open_url(url)
        return {"message": str(msg), "data": {"url": url}}

    if ntype == "apps.open_app":
        app = cfg.get("app") or "notepad"
        msg = computer.open_app(app)
        return {"message": str(msg), "data": {"app": app}}

    if ntype == "data.transform":
        name = cfg.get("name") or "custom"
        val = cfg.get("template") or ""
        ctx.setdefault("variables", {})[name] = val
        return {"message": f"Set {name} = {val[:200]}", "data": {"name": name, "value": val}}

    if ntype in {"ai.agent", "ai.summarize", "ai.classify"}:
        if not flows_catalog.is_implemented(ntype):
            raise RuntimeError(f"NOT IMPLEMENTED: {ntype}")
        result = _exec_ai(settings, ntype, cfg, ctx)
        return result

    if ntype == "service.http_request":
        return _exec_http_request(cfg)

    if ntype == "service.email_send":
        return _exec_email_send(settings, cfg)

    if ntype == "service.slack_message":
        return _exec_slack_message(cfg)

    if ntype == "data.database_query":
        return _exec_database_query(settings, cfg)

    if not flows_catalog.is_implemented(ntype):
        raise RuntimeError(f"NOT IMPLEMENTED: {ntype}")

    raise RuntimeError(f"Unknown or unsupported node type: {ntype}")


def _exec_http_request(cfg: dict) -> dict[str, Any]:
    import httpx

    from altron.adapters.mcp_fetch import is_public_http_url

    url = (cfg.get("url") or "").strip()
    if not is_public_http_url(url):
        raise RuntimeError("Blocked: only public http(s) URLs. No localhost, file, or private IPs.")
    method = (cfg.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise RuntimeError(f"Unsupported HTTP method: {method}")
    headers: dict = {}
    raw_headers = (cfg.get("headers") or "").strip()
    if raw_headers:
        try:
            headers = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid headers JSON: {exc}") from exc
    body_raw = (cfg.get("body") or "").strip()
    json_body = None
    data_body = None
    if body_raw:
        try:
            json_body = json.loads(body_raw)
        except json.JSONDecodeError:
            data_body = body_raw
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.request(method, url, headers=headers, json=json_body, content=data_body)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"HTTP request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    text = resp.text[:8000]
    return {
        "message": f"{method} {url} -> {resp.status_code}",
        "data": {"status": resp.status_code, "json": payload, "text": text},
    }


def _exec_email_send(settings, cfg: dict) -> dict[str, Any]:
    import smtplib
    from email.mime.text import MIMEText

    to_addr = (cfg.get("to") or "").strip()
    if not to_addr:
        raise RuntimeError("Send Email: 'to' is required")
    host = (getattr(settings, "smtp_host", "") or "").strip()
    if not host:
        raise RuntimeError("Send Email: SMTP not configured — set SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS in .env")
    port = int(getattr(settings, "smtp_port", 0) or 587)
    user = (getattr(settings, "smtp_user", "") or "").strip()
    password = (getattr(settings, "smtp_pass", "") or "").strip()
    from_addr = (getattr(settings, "smtp_from", "") or user or "altron@localhost").strip()

    subject = cfg.get("subject") or "(no subject)"
    body = cfg.get("body") or ""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"SMTP send failed: {exc}") from exc
    return {"message": f"Email sent to {to_addr}", "data": {"sent": True, "to": to_addr}}


def _exec_slack_message(cfg: dict) -> dict[str, Any]:
    import httpx

    from altron.adapters.mcp_fetch import is_public_http_url

    webhook_url = (cfg.get("webhook_url") or "").strip()
    if not is_public_http_url(webhook_url):
        raise RuntimeError("Slack: webhook_url must be a public https:// URL")
    message = cfg.get("message") or ""
    try:
        resp = httpx.post(webhook_url, json={"text": message}, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Slack post failed: {exc}") from exc
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack webhook returned HTTP {resp.status_code}")
    return {"message": "Slack message sent", "data": {"sent": True, "status": resp.status_code}}


def _exec_database_query(settings, cfg: dict) -> dict[str, Any]:
    import sqlite3

    db_path = (cfg.get("db_path") or "").strip()
    if not db_path:
        raise RuntimeError("Database Query: db_path is required")
    resolved = pc_roots.resolve_in_roots(settings, db_path)
    if resolved is None:
        raise RuntimeError(f"Blocked path (not a trusted root): {db_path}")
    sql = (cfg.get("sql") or "").strip()
    if not sql:
        raise RuntimeError("Database Query: sql is required")
    params: list = []
    raw_params = (cfg.get("params") or "").strip()
    if raw_params:
        try:
            params = json.loads(raw_params)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid params JSON: {exc}") from exc
    try:
        conn = sqlite3.connect(str(resolved))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            if cur.description:
                rows = [dict(r) for r in cur.fetchall()[:500]]
            else:
                rows = []
            conn.commit()
            rowcount = cur.rowcount
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"SQL error: {exc}") from exc
    return {
        "message": f"Query returned {len(rows)} row(s)",
        "data": {"rows": rows, "row_count": len(rows), "rowcount": rowcount},
    }


def _ai_input_text(cfg: dict, ctx: dict) -> str:
    raw = (cfg.get("input_var") or "").strip()
    if raw:
        if "{{" in raw:
            return _resolve_template(raw, ctx)
        # treat as variable path without braces
        looked = _lookup_path(ctx, [p for p in raw.replace("$", "").split(".") if p])
        if looked not in ("", None):
            return _stringify(looked)
        return raw
    prev = ctx.get("last_output")
    if isinstance(prev, dict):
        if prev.get("text"):
            return str(prev.get("text"))[:6000]
        if prev.get("files") is not None or prev.get("entries") is not None:
            files = prev.get("files") or [e for e in (prev.get("entries") or []) if e.get("type") == "file"]
            names = [f.get("name") for f in files[:40]]
            return (
                f"Folder listing ({prev.get('file_count', len(files))} files):\n"
                + "\n".join(names)
                + ("\n…" if len(files) > 40 else "")
            )
        if prev.get("logged"):
            return str(prev.get("logged"))[:6000]
        return _stringify(prev)[:6000]
    text = ctx.get("variables", {}).get("file.text") or ""
    return str(text)[:6000]


def _exec_ai(settings, ntype: str, cfg: dict, ctx: dict) -> dict[str, Any]:
    from altron.adapters.think import ThinkAdapter

    text = _ai_input_text(cfg, ctx)
    schema_keys = [k.strip() for k in str(cfg.get("schema") or "classification,confidence,summary").split(",") if k.strip()]
    schema_hint = (
        "Respond with ONLY a single JSON object (no markdown) matching this schema exactly:\n"
        + json.dumps({k: ("string" if k != "confidence" else "number 0..1") for k in schema_keys}, indent=2)
        + "\nDo not wrap in ```."
    )

    if ntype == "ai.summarize":
        prompt = (
            f"Summarize the input. {schema_hint}\n"
            f'Use classification="summary", confidence 0-1, summary=your brief summary.\n\n{text[:6000]}'
        )
        default_var = "ai.summary"
    elif ntype == "ai.classify":
        labels = cfg.get("labels") or "other"
        prompt = (
            f"Classify into exactly one of [{labels}]. {schema_hint}\n"
            f"Set classification to the chosen label.\n\n{text[:6000]}"
        )
        default_var = "ai.label"
    else:
        base = cfg.get("prompt") or "Analyze the input and return useful structured findings."
        prompt = f"{base}\n\n{schema_hint}"
        if text:
            prompt = f"{prompt}\n\nInput:\n{text[:6000]}"
        default_var = "ai.result"

    think = ThinkAdapter(settings)
    try:
        reply = think.complete([{"role": "user", "content": prompt}])
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ALTRON AI error: {exc}") from exc
    reply = str(reply or "").strip()
    if not reply:
        raise RuntimeError("ALTRON AI returned empty response")

    structured = _parse_ai_json(reply, schema_keys)
    if structured is None:
        # one repair attempt
        repair = (
            "Convert the following into ONLY valid JSON with keys "
            + ", ".join(schema_keys)
            + f".\n\n{reply[:4000]}"
        )
        try:
            reply2 = think.complete([{"role": "user", "content": repair}])
            structured = _parse_ai_json(str(reply2 or ""), schema_keys)
            if structured:
                reply = str(reply2).strip()
        except Exception:  # noqa: BLE001
            structured = None
    strict = str(cfg.get("strict") or "").strip().lower() in {"1", "true", "yes", "on"}
    if structured is None:
        if strict:
            raise RuntimeError("AI JSON schema validation failed (strict mode) — refusing to fabricate output")
        # Phase-1 soft fallback: wrap plain text into required schema
        structured = {
            "classification": "unstructured",
            "confidence": 0.4,
            "summary": reply[:800],
        }
        for k in schema_keys:
            structured.setdefault(k, "" if k != "confidence" else 0.4)
        structured = {k: structured.get(k) for k in schema_keys}
        reply = json.dumps(structured)

    # validate required keys + confidence range
    missing = [k for k in schema_keys if k not in structured]
    if missing:
        raise RuntimeError(f"AI JSON missing keys: {missing}")
    if "confidence" in structured:
        try:
            conf = float(structured["confidence"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("AI JSON confidence must be a number") from exc
        structured["confidence"] = max(0.0, min(1.0, conf))

    # Normalize aliases for branching (category ↔ classification)
    if "category" in structured and "classification" not in structured:
        structured["classification"] = structured["category"]
    if "classification" in structured and "category" not in structured:
        structured["category"] = structured["classification"]

    out_var = (cfg.get("output_var") or default_var).replace("$", "").strip() or default_var
    ctx.setdefault("variables", {})[out_var] = structured
    ctx.setdefault("variables", {})["ai.result"] = structured
    ctx.setdefault("variables", {})["ai.classification"] = structured.get("classification") or structured.get("category")
    ctx.setdefault("variables", {})["ai.confidence"] = structured.get("confidence")
    ctx.setdefault("variables", {})["category"] = structured.get("category") or structured.get("classification")
    ctx.setdefault("variables", {})["confidence"] = structured.get("confidence")
    data = {
        "text": reply[:2000],
        "json": structured,
        "output_var": out_var,
        "model": "ALTRON",
        "input_chars": len(text),
        "schema_ok": True,
        "strict": strict,
    }
    return {"message": json.dumps(structured)[:500], "data": data}


def _parse_ai_json(reply: str, schema_keys: list[str]) -> dict | None:
    raw = (reply or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # extract first {...}
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    # must contain at least classification or all schema keys partially
    if not any(k in obj for k in schema_keys):
        return None
    return obj


def _eval_condition(cond: str, ctx: dict) -> bool:
    raw = _resolve_template((cond or "").strip(), ctx).strip()
    if not raw:
        return False
    low = raw.lower()

    # numeric compare: count > 0, filter.count >= 1, list.file_count == 0
    m = re.match(
        r"^(?:variables\.)?(count|filter\.count|filter\.file_count|list\.count|list\.file_count|file_count)\s*(>=|<=|==|!=|>|<)\s*(-?\d+)$",
        low,
    )
    if m:
        key, op, num_s = m.group(1), m.group(2), m.group(3)
        num = int(num_s)
        vals = ctx.get("variables") or {}
        key_map = {
            "count": vals.get("filter.count", vals.get("list.count", 0)),
            "filter.count": vals.get("filter.count", 0),
            "filter.file_count": vals.get("filter.file_count", 0),
            "list.count": vals.get("list.count", 0),
            "list.file_count": vals.get("list.file_count", 0),
            "file_count": vals.get("list.file_count", vals.get("filter.file_count", 0)),
        }
        left = int(key_map.get(key, 0) or 0)
        ops = {
            ">": left > num,
            "<": left < num,
            ">=": left >= num,
            "<=": left <= num,
            "==": left == num,
            "!=": left != num,
        }
        return bool(ops[op])

    if "==" in raw:
        a, b = raw.split("==", 1)
        return a.strip().lower() == b.strip().strip("'\"").lower()
    if "!=" in raw:
        a, b = raw.split("!=", 1)
        return a.strip().lower() != b.strip().strip("'\"").lower()
    if "contains" in low:
        # "contains .pdf" against listing names, or "haystack contains needle"
        if low.startswith("contains "):
            needle = raw.split(" ", 1)[1].strip().strip("'\"").lower()
            listing = ctx.get("last_listing") or []
            return any(needle in str(e.get("name", "")).lower() for e in listing)
        parts = re.split(r"\s+contains\s+", raw, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            return parts[1].strip().strip("'\"").lower() in parts[0].strip().lower()

    ext = str(ctx.get("file", {}).get("extension") or "").lower()
    if low in {"pdf", "is pdf", "extension == pdf"}:
        return ext == "pdf" or any(str(e.get("name", "")).lower().endswith(".pdf") for e in (ctx.get("last_listing") or []))

    # truthy non-empty / true / yes / 1
    if low in {"true", "yes", "1"}:
        return True
    if low in {"false", "no", "0"}:
        return False
    return bool(raw)


def _copy_or_move(settings, cfg: dict, ctx: dict, move: bool) -> str:
    src = pc_roots.resolve_in_roots(settings, str(cfg.get("src") or ""))
    dst_dir = pc_roots.resolve_in_roots(settings, str(cfg.get("dst_dir") or ""))
    if src is None or not src.is_file():
        raise RuntimeError("Source file blocked or missing")
    if dst_dir is None or not dst_dir.is_dir():
        raise RuntimeError("Destination folder blocked or missing")
    dest = dst_dir / src.name
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(str(src), str(dest))
    ctx["last_path"] = str(dest)
    ctx["file"] = {"path": str(dest), "name": dest.name, "extension": dest.suffix.lstrip(".")}
    return f"{'Moved' if move else 'Copied'} → {dest}"
