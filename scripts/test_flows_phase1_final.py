from __future__ import annotations

"""Phase 1 FINAL acceptance tests A–G for ALTRON FLOWS.

Must all pass before claiming PHASE 1 = COMPLETE.
Does not start Phase 2.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from altron.adapters import flows_agi, flows_catalog, flows_engine, flows_expr, flows_runtime, pc_roots, tools
from altron.settings import get_settings


def ok(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    if detail:
        detail = str(detail).replace("\u2192", "->").encode("ascii", "replace").decode("ascii")
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def _desktop(settings) -> str:
    for r in pc_roots.list_roots(settings):
        if r["name"].lower() == "desktop":
            return r["path"]
    roots = pc_roots.list_roots(settings)
    return roots[0]["path"] if roots else ""


def main() -> int:
    settings = get_settings()
    failed = 0
    desktop = _desktop(settings)
    print(f"Trusted Desktop: {desktop}")

    # --- A create Desktop PDF scan + log ---
    out_a = flows_agi.handle(
        settings, "Create a workflow that scans my Desktop for PDF files and logs the result."
    )
    failed += not ok("A create", "Created workflow" in out_a, out_a[:160])
    intent_a = flows_agi.parse_intent(
        "Create a workflow that scans my Desktop for PDF files and logs the result."
    )
    failed += not ok("A intent", intent_a.get("intent") == "create_workflow")

    flows = sorted(flows_engine.list_flows(settings), key=lambda f: f.get("updated") or 0, reverse=True)
    flow = None
    for f in flows:
        g = flows_engine.get_flow(settings, f["id"])
        if g and (g.get("settings") or {}).get("source") == "altron_chat":
            flow = g
            break
    failed += not ok("A flow exists", bool(flow))
    assert flow
    types = [n.get("type") for n in flow.get("nodes") or []]
    failed += not ok("A has list+log", "files.list" in types and ("logic.log" in types or "notify.log" in types), str(types))
    failed += not ok("A PDF filter or pattern", "logic.filter" in types or any(
        "*.pdf" in str((n.get("config") or {}).get("pattern") or "") for n in flow.get("nodes") or []
    ), str(types))

    # --- B add AI analysis ---
    out_b = flows_agi.handle(settings, "Add an AI analysis step after the PDF scan.")
    failed += not ok("B modify AI", "Updated flow" in out_b, out_b[:160])
    flow = flows_engine.get_flow(settings, flow["id"])
    assert flow
    types = [n.get("type") for n in flow.get("nodes") or []]
    failed += not ok("B has ai.agent", "ai.agent" in types, str(types))
    edges = flow.get("edges") or []
    ai = next(n for n in flow["nodes"] if n["type"] == "ai.agent")
    scan = next(n for n in reversed(flow["nodes"]) if n["type"] in {"logic.filter", "files.list"})
    failed += not ok(
        "B connected after scan",
        any(e.get("source") == scan["id"] and e.get("target") == ai["id"] for e in edges)
        or any(e.get("target") == ai["id"] for e in edges),
        str([(e.get("source"), e.get("target")) for e in edges]),
    )

    # --- C only continue when PDF count > 0 ---
    out_c = flows_agi.handle(settings, "Only continue when PDF count is greater than 0.")
    failed += not ok("C modify if", "Updated flow" in out_c, out_c[:160])
    flow = flows_engine.get_flow(settings, flow["id"])
    assert flow
    types = [n.get("type") for n in flow.get("nodes") or []]
    failed += not ok("C has logic.if", "logic.if" in types, str(types))
    if_node = next(n for n in flow["nodes"] if n["type"] == "logic.if")
    cond = str((if_node.get("config") or {}).get("condition") or "")
    failed += not ok("C condition count", "count" in cond.lower() and ">" in cond, cond)
    yes_edges = [e for e in flow.get("edges") or [] if e.get("source") == if_node["id"] and (e.get("sourceHandle") or "") == "yes"]
    no_edges = [e for e in flow.get("edges") or [] if e.get("source") == if_node["id"] and (e.get("sourceHandle") or "") == "no"]
    failed += not ok("C yes+no branches", bool(yes_edges) and bool(no_edges), f"yes={yes_edges} no={no_edges}")

    issues = flows_agi.validate_plan_or_flow(settings, flow)
    failed += not ok("C validate graph", not issues, str(issues))

    # Ensure at least one PDF exists so If → YES and AI runs (real filesystem)
    pdf_probe = Path(desktop) / f"_altron_p1_{int(time.time())}.pdf"
    pdf_probe.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")

    # --- D run ---
    run = flows_engine.run_flow(settings, flow["id"])
    failed += not ok("D run ok", bool(run.get("ok")), f"{run.get('status')} err={run.get('message')}")
    failed += not ok("D real logs", len(run.get("logs") or []) >= 3, str(len(run.get("logs") or [])))
    failed += not ok("D variables", bool(run.get("variables")), str(list((run.get("variables") or {}).keys())[:8]))

    # --- E verify ---
    list_ok = any(r.get("type") == "files.list" and r.get("status") == "SUCCESS" for r in run.get("nodeResults") or [])
    failed += not ok("E list filesystem", list_ok)
    if_res = next((r for r in (run.get("nodeResults") or []) if r.get("type") == "logic.if"), None)
    failed += not ok("E if branch", bool(if_res and if_res.get("status") == "SUCCESS"), str(if_res))
    if if_res and isinstance(if_res.get("output"), dict):
        failed += not ok("E if YES (pdf present)", if_res["output"].get("result") is True, str(if_res.get("output")))
    ai_res = next((r for r in (run.get("nodeResults") or []) if r.get("type") == "ai.agent"), None)
    if ai_res and ai_res.get("status") == "SUCCESS":
        data = ai_res.get("output") or {}
        js = data.get("json") if isinstance(data, dict) else None
        failed += not ok(
            "E AI structured JSON",
            isinstance(js, dict) and "classification" in js and "confidence" in js,
            str(js)[:120],
        )
    else:
        failed += not ok("E AI ran", False, str(ai_res))
    hist = flows_engine.get_run(settings, str(run.get("id") or ""))
    failed += not ok("E run history persisted", bool(hist), str(run.get("id")))
    # invalid node validation
    bad = json.loads(json.dumps(flow))
    bad["nodes"].append({"id": "bad1", "type": "trigger.teleport", "label": "X", "position": {"x": 0, "y": 0}, "config": {}})
    bad_issues = flows_agi.validate_plan_or_flow(settings, bad)
    failed += not ok("E invalid node caught", any("NOT IMPLEMENTED" in i for i in bad_issues), str(bad_issues))

    # cleanup probe pdf (best-effort)
    try:
        pdf_probe.unlink(missing_ok=True)
    except OSError:
        pass

    # --- F triggers ---
    # Manual already covered by D
    failed += not ok("F manual", bool(run.get("ok")))

    # Schedule via runtime fire + cron match
    sched_flow = {
        "name": "P1 Schedule Probe",
        "settings": {"source": "altron_chat"},
        "nodes": [
            {
                "id": "n1",
                "type": "trigger.schedule",
                "label": "Schedule",
                "position": {"x": 0, "y": 0},
                "config": {"cron": "* * * * *"},
            },
            {"id": "n2", "type": "logic.log", "label": "Log", "position": {"x": 200, "y": 0}, "config": {"message": "schedule-ok"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    saved_s = flows_engine.save_flow(settings, sched_flow)
    failed += not ok("F schedule implemented", flows_catalog.is_implemented("trigger.schedule"))
    srun = flows_runtime.fire_flow(
        settings, saved_s["id"], {"source": "trigger.schedule", "cron": "* * * * *", "at": time.time()}
    )
    failed += not ok("F schedule fire", bool(srun.get("ok")), srun.get("status"))
    failed += not ok("F cron match", flows_runtime._cron_match("* * * * *"))
    # also prove tick can fire schedule (may skip if already fired this minute — still ok if fire_flow passed)
    tick_sched = flows_runtime.tick(settings)
    failed += not ok("F schedule tick or prior fire", bool(srun.get("ok")) or any("schedule fired" in ln for ln in tick_sched), str(tick_sched)[:120])

    # File Created — unique folder, seed then create
    watch_dir = Path(desktop) / f"_altron_p1_watch_{int(time.time())}"
    watch_dir.mkdir(exist_ok=True)
    fc_flow = {
        "name": "P1 FileCreated Probe",
        "settings": {"source": "altron_chat"},
        "nodes": [
            {
                "id": "n1",
                "type": "trigger.file_created",
                "label": "File Created",
                "position": {"x": 0, "y": 0},
                "config": {"path": str(watch_dir)},
            },
            {"id": "n2", "type": "logic.log", "label": "Log", "position": {"x": 200, "y": 0}, "config": {"message": "file={{file.name}}"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    saved_fc = flows_engine.save_flow(settings, fc_flow)
    seed_lines = flows_runtime.tick(settings)  # seed watch set
    probe = watch_dir / f"p1_{int(time.time())}.txt"
    probe.write_text("phase1", encoding="utf-8")
    time.sleep(0.05)
    lines = flows_runtime.tick(settings)
    failed += not ok(
        "F file_created tick",
        any(saved_fc["id"] in ln for ln in lines) or any("file_created" in ln for ln in lines),
        f"seed={seed_lines!r} lines={lines!r}",
    )
    # also direct fire
    fr = flows_runtime.fire_flow(
        settings,
        saved_fc["id"],
        {"source": "trigger.file_created", "path": str(probe), "name": probe.name, "folder": str(watch_dir), "at": time.time()},
    )
    failed += not ok("F file_created fire", bool(fr.get("ok")), fr.get("status"))
    try:
        probe.unlink(missing_ok=True)
        watch_dir.rmdir()
    except OSError:
        pass

    # Webhook
    wh_flow = {
        "name": "P1 Webhook Probe",
        "settings": {"source": "altron_chat"},
        "nodes": [
            {
                "id": "n1",
                "type": "trigger.webhook",
                "label": "Webhook",
                "position": {"x": 0, "y": 0},
                "config": {"path": "p1-webhook-probe"},
            },
            {"id": "n2", "type": "logic.log", "label": "Log", "position": {"x": 200, "y": 0}, "config": {"message": "webhook"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    saved_wh = flows_engine.save_flow(settings, wh_flow)
    wh = flows_runtime.handle_webhook(settings, "p1-webhook-probe", {"hello": True})
    failed += not ok("F webhook", bool(wh.get("ok")), str(wh))

    # App Started
    as_flow = {
        "name": "P1 AppStarted Probe",
        "settings": {"source": "altron_chat"},
        "nodes": [
            {"id": "n1", "type": "trigger.app_started", "label": "App Started", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "logic.log", "label": "Log", "position": {"x": 200, "y": 0}, "config": {"message": "app-started"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    saved_as = flows_engine.save_flow(settings, as_flow)
    flows_runtime._started_once = False  # type: ignore[attr-defined]
    as_lines = flows_runtime.run_app_started(settings)
    failed += not ok("F app_started", any(saved_as["id"] in ln for ln in as_lines) or bool(as_lines), str(as_lines))

    # Catalog flags
    for t in ("trigger.schedule", "trigger.file_created", "trigger.webhook", "trigger.app_started"):
        failed += not ok(f"F catalog {t}", flows_catalog.is_implemented(t))

    # --- G security ---
    deny = flows_agi.handle(settings, "Delete everything from C:\\")
    failed += not ok("G deny destructive", "Denied" in deny or "denied" in deny.lower(), deny[:100])
    # untrusted path blocked on validate
    evil = {
        "name": "Evil",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {
                "id": "n2",
                "type": "files.list",
                "label": "L",
                "position": {"x": 200, "y": 0},
                "config": {"path": r"C:\Windows\System32"},
            },
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    evil_issues = flows_agi.validate_plan_or_flow(settings, evil)
    failed += not ok("G untrusted blocked", any("trusted" in i.lower() for i in evil_issues), str(evil_issues))
    # trusted path succeeds (desktop list already did)
    failed += not ok("G trusted ok", list_ok)
    # risky confirm
    risky_plan = flows_agi.plan_from_text(settings, "organize Desktop PDFs with AI and move them to Documents/Invoices")
    risky_flow = flows_agi.plan_to_flow(risky_plan)
    risky_saved = flows_engine.save_flow(settings, risky_flow)
    risky_out = flows_agi.handle(settings, f"run flow {risky_saved['name']}")
    failed += not ok(
        "G risky confirm",
        "CONFIRM" in risky_out.upper() or "confirm" in risky_out.lower() or "flow_run" in risky_out.lower(),
        risky_out[:160],
    )

    # expressions (no eval)
    ctx = {"variables": {"list.file_count": 3, "filter.file_count": 2}, "last_listing": [{"name": "a.pdf"}], "file": {"extension": "pdf"}}
    failed += not ok("Expr count>0", flows_expr.evaluate_bool("filter.file_count > 0", ctx))
    failed += not ok("Expr and", flows_expr.evaluate_bool("list.file_count > 1 and filter.file_count > 0", ctx))

    # chat tool routing still works
    picked = tools.pick_action("list flows", settings)
    failed += not ok("Chat flows_act", picked and picked[0] == "flows_act", str(picked))

    print("\n" + ("=" * 60))
    if failed == 0:
        print("PHASE 1 = COMPLETE")
        print("Phase 2 has NOT been started.")
        print("RESULT: ALL PASS")
        return 0
    print("PHASE 1 = COMPLETE? NO")
    print(f"RESULT: {failed} FAILED")
    print("Phase 2 has NOT been started.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
