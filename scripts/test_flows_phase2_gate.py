from __future__ import annotations

"""Phase 2 GATE — real end-to-end validation (not demo checkboxes).

Produces a truthful PASS/FAIL matrix. Does not claim Phase 2 COMPLETE.
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from altron.adapters import (
    flows_agi,
    flows_catalog,
    flows_engine,
    flows_expr,
    flows_planner,
    flows_runtime,
    pc_roots,
    safety,
    tools,
)
from altron.adapters.memory import JsonlMemory
from altron.settings import get_settings


def ascii(s: str) -> str:
    return str(s).replace("\u2192", "->").encode("ascii", "replace").decode("ascii")


def ok(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {ascii(detail)}" if detail else ""))
    return cond


def root_named(settings, name: str) -> str:
    for r in pc_roots.list_roots(settings):
        if r["name"].lower() == name.lower():
            return r["path"]
    roots = pc_roots.list_roots(settings)
    return roots[0]["path"] if roots else ""


def main() -> int:
    settings = get_settings()
    gate: dict[str, bool] = {}
    desktop = root_named(settings, "Desktop")
    downloads = root_named(settings, "Downloads")
    docs = root_named(settings, "Documents")
    work = Path(desktop) / f"_altron_p2_gate_{int(time.time())}"
    work.mkdir(exist_ok=True)
    print(f"GATE workdir: {work}")

    # ---------- PHASE 1 (quick smoke via import of final markers) ----------
    # Full suite run separately; here we assert catalog triggers still live
    p1 = True
    for t in ("trigger.manual", "trigger.schedule", "trigger.file_created", "trigger.webhook", "trigger.app_started"):
        p1 = p1 and flows_catalog.is_implemented(t)
    gate["PHASE 1"] = ok("PHASE1 catalog triggers live", p1)

    # ---------- 1 NL -> FLOW ----------
    nl = (
        "Create a workflow that scans Downloads for PDFs, analyzes them with ALTRON AI, "
        "renames them and moves them to an appropriate trusted folder."
    )
    out = flows_agi.handle(settings, nl)
    created = "Created workflow" in out
    # prefer id from response
    m = re.search(r"\((flow_[a-f0-9]+|[a-f0-9]{8,})\)", out)
    flow = None
    if m:
        flow = flows_engine.get_flow(settings, m.group(1))
    if flow is None:
        flows = sorted(flows_engine.list_flows(settings), key=lambda f: f.get("updated") or 0, reverse=True)
        for f in flows:
            g = flows_engine.get_flow(settings, f["id"])
            if g and (g.get("settings") or {}).get("source") == "altron_chat":
                flow = g
                break
    types = [n.get("type") for n in (flow or {}).get("nodes") or []]
    has_scan = "files.list" in types or "trigger.file_created" in types
    has_ai = any(str(t).startswith("ai.") for t in types)
    has_act = "files.rename" in types or "files.move" in types
    persisted = flow is not None and bool(flows_engine.get_flow(settings, flow["id"]))
    # edges exist and all types catalog-valid
    allowed = set(flows_planner.catalog_types())
    catalog_ok = all(t in allowed for t in types) and len(flow.get("edges") or []) >= 1 if flow else False
    nl_ok = created and persisted and has_scan and has_ai and has_act and catalog_ok
    gate["NL -> FLOW"] = ok(
        "1 NL->FLOW persisted",
        nl_ok,
        f"types={types} edges={len((flow or {}).get('edges') or [])} out={out[:100]}",
    )
    if not flow:
        print("FATAL: no flow after NL create")
        return 1

    # ---------- 2 NL EDIT ----------
    # Build clean editable flow: Manual->List->AI->Move->Log
    edit = {
        "name": "GATE Edit Base",
        "settings": {"source": "altron_chat", "phase": 2, "ai_generated": True},
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "Manual", "position": {"x": 0, "y": 0}, "config": {}},
            {
                "id": "n2",
                "type": "files.list",
                "label": "List",
                "position": {"x": 200, "y": 0},
                "config": {"path": str(work)},
            },
            {
                "id": "n3",
                "type": "ai.agent",
                "label": "AI",
                "position": {"x": 400, "y": 0},
                "config": {
                    "prompt": "Classify",
                    "schema": "category,confidence,summary,suggested_name",
                    "strict": "true",
                },
            },
            {
                "id": "n4",
                "type": "files.move",
                "label": "Move",
                "position": {"x": 600, "y": 0},
                "config": {"src": "{{item.path}}", "dst_dir": str(Path(docs) / "Other")},
            },
            {"id": "n5", "type": "logic.log", "label": "Log", "position": {"x": 800, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e4", "source": "n4", "target": "n5", "sourceHandle": "default", "targetHandle": "in"},
        ],
    }
    edit = flows_engine.save_flow(settings, edit)
    e1 = flows_agi.modify_flow_from_text(settings, edit, "Add a PDF filter before AI.")
    e1 = flows_engine.save_flow(settings, e1)
    t1 = [n.get("type") for n in e1["nodes"]]
    e2 = flows_agi.modify_flow_from_text(settings, e1, "Remove the move step.")
    e2 = flows_engine.save_flow(settings, e2)
    t2 = [n.get("type") for n in e2["nodes"]]
    e3 = flows_agi.modify_flow_from_text(settings, e2, "Add an IF where confidence is below 0.8.")
    e3 = flows_engine.save_flow(settings, e3)
    ifn = next((n for n in e3["nodes"] if n.get("type") == "logic.if"), None)
    cond = str((ifn or {}).get("config", {}).get("condition") or "")
    e4 = flows_agi.modify_flow_from_text(settings, e3, "Rename the workflow to GATE Edited Flow")
    e4 = flows_engine.save_flow(settings, e4)
    edit_ok = (
        "logic.filter" in t1
        and "files.move" not in t2
        and ifn is not None
        and "confidence" in cond
        and "<" in cond
        and e4.get("name") == "GATE Edited Flow"
    )
    gate["NL EDIT"] = ok("2 NL EDIT graph changed", edit_ok, f"t1={t1} t2={t2} cond={cond} name={e4.get('name')}")

    # ---------- 3 DATA MAPPING ----------
    for i in range(2):
        (work / f"map_{i}.txt").write_text(f"invoice content {i}", encoding="utf-8")
    map_flow = {
        "name": "GATE Map",
        "settings": {"source": "altron_chat"},
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "files.list", "label": "List", "position": {"x": 200, "y": 0}, "config": {"path": str(work)}},
            {"id": "n3", "type": "logic.filter", "label": "Filter", "position": {"x": 400, "y": 0}, "config": {"pattern": ".txt"}},
            {
                "id": "n4",
                "type": "logic.log",
                "label": "Log",
                "position": {"x": 600, "y": 0},
                "config": {"message": "filtered={{variables.filter.file_count}} list={{variables.list.file_count}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default", "targetHandle": "in"},
        ],
    }
    map_saved = flows_engine.save_flow(settings, map_flow)
    map_run = flows_engine.run_flow(settings, map_saved["id"])
    log_msg = next((r.get("message") for r in map_run.get("nodeResults") or [] if r.get("nodeId") == "n4"), "")
    map_ok = bool(map_run.get("ok")) and "filtered=" in str(log_msg) and "list=" in str(log_msg)
    # ensure not hardcoded zeros-only nonsense: filter count should be >= 2
    map_ok = map_ok and "filtered=0" not in str(log_msg)
    gate["DATA MAPPING"] = ok("3 DATA MAPPING", map_ok, str(log_msg))

    # ---------- 4 FOREACH ----------
    for i in range(5):
        (work / f"loop_{i}.txt").write_text(f"item-{i}", encoding="utf-8")
    loop_flow = {
        "name": "GATE Loop",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {
                "id": "n2",
                "type": "files.list",
                "label": "L",
                "position": {"x": 200, "y": 0},
                "config": {"path": str(work), "pattern": "loop_"},
            },
            {"id": "n3", "type": "logic.foreach", "label": "Each", "position": {"x": 400, "y": 0}, "config": {"max": "20"}},
            {"id": "n4", "type": "logic.log", "label": "Item", "position": {"x": 600, "y": 0}, "config": {"message": "{{item.name}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default", "targetHandle": "in"},
        ],
    }
    loop_saved = flows_engine.save_flow(settings, loop_flow)
    loop_run = flows_engine.run_flow(settings, loop_saved["id"])
    fe = loop_run.get("foreach") or {}
    item_ok = [r for r in (loop_run.get("nodeResults") or []) if r.get("nodeId") == "n4" and r.get("status") == "SUCCESS"]
    # pattern loop_ may match 5 files
    foreach_ok = len(item_ok) >= 5 and int(fe.get("total") or 0) >= 5 and int(fe.get("success") or 0) >= 5
    gate["FOREACH"] = ok("4 FOREACH", foreach_ok, f"iters={len(item_ok)} metrics={fe}")

    # ---------- 5 IF/ELSE both branches + SKIPPED ----------
    # TRUE branch
    if_true = {
        "name": "GATE If True",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "logic.if", "label": "If", "position": {"x": 200, "y": 0}, "config": {"condition": "true"}},
            {"id": "n3", "type": "logic.log", "label": "YesLog", "position": {"x": 400, "y": 0}, "config": {"message": "YES"}},
            {"id": "n4", "type": "logic.log", "label": "NoLog", "position": {"x": 400, "y": 120}, "config": {"message": "NO"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "yes", "targetHandle": "in", "label": "Yes"},
            {"id": "e3", "source": "n2", "target": "n4", "sourceHandle": "no", "targetHandle": "in", "label": "No"},
        ],
    }
    if_false = json.loads(json.dumps(if_true))
    if_false["name"] = "GATE If False"
    if_false["nodes"][1]["config"]["condition"] = "false"
    st = flows_engine.save_flow(settings, if_true)
    sf = flows_engine.save_flow(settings, if_false)
    rt = flows_engine.run_flow(settings, st["id"])
    rf = flows_engine.run_flow(settings, sf["id"])
    t_yes = next((r for r in rt.get("nodeResults") or [] if r.get("nodeId") == "n3"), None)
    t_no = next((r for r in rt.get("nodeResults") or [] if r.get("nodeId") == "n4"), None)
    f_yes = next((r for r in rf.get("nodeResults") or [] if r.get("nodeId") == "n3"), None)
    f_no = next((r for r in rf.get("nodeResults") or [] if r.get("nodeId") == "n4"), None)
    if_ok = (
        t_yes
        and t_yes.get("status") == "SUCCESS"
        and t_no
        and t_no.get("status") == "SKIPPED"
        and f_no
        and f_no.get("status") == "SUCCESS"
        and f_yes
        and f_yes.get("status") == "SKIPPED"
    )
    gate["IF/ELSE"] = ok(
        "5 IF/ELSE both branches",
        if_ok,
        f"true:yes={t_yes and t_yes.get('status')} no={t_no and t_no.get('status')} "
        f"false:yes={f_yes and f_yes.get('status')} no={f_no and f_no.get('status')}",
    )

    # expression confidence
    ctx = {"variables": {"ai.result": {"confidence": 0.5, "category": "other"}, "confidence": 0.5, "category": "other"}}
    gate["IF/ELSE"] = gate["IF/ELSE"] and ok("5 expr confidence < 0.8", flows_expr.evaluate_bool("confidence < 0.8", ctx))

    # ---------- 6 AI AGENT ----------
    ai_ok_flow = {
        "name": "GATE AI OK",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {
                "id": "n2",
                "type": "ai.agent",
                "label": "AI",
                "position": {"x": 200, "y": 0},
                "config": {
                    "prompt": "Classify as invoice. Text: Electricity bill.",
                    "input_var": "Electricity bill September 2026",
                    "schema": "category,confidence,summary,suggested_name",
                    "strict": "true",
                },
            },
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    ai_saved = flows_engine.save_flow(settings, ai_ok_flow)
    ai_run = flows_engine.run_flow(settings, ai_saved["id"])
    ai_res = next((r for r in ai_run.get("nodeResults") or [] if r.get("type") == "ai.agent"), None)
    js = ((ai_res or {}).get("output") or {}).get("json")
    valid_ai = bool(ai_run.get("ok")) and isinstance(js, dict) and "category" in js and "confidence" in js

    from altron.adapters import think as think_mod

    real = think_mod.ThinkAdapter

    class FakeThink:
        def __init__(self, settings):
            pass

        def complete(self, messages):
            return "NOT JSON {{{"

    think_mod.ThinkAdapter = FakeThink  # type: ignore
    try:
        bad = flows_engine.test_node(
            settings,
            {"type": "ai.agent", "config": {"prompt": "x", "schema": "category,confidence", "strict": "true", "input_var": "hi"}},
            {},
        )
        invalid_ai = bad.get("ok") is False and "schema" in str(bad.get("error") or "").lower()
    finally:
        think_mod.ThinkAdapter = real  # type: ignore

    gate["AI AGENT"] = ok("6 AI AGENT valid+invalid", valid_ai and invalid_ai, f"js={js} bad={bad}")

    # ---------- 7 SAFETY ----------
    safety.clear(settings.safety_path)
    risky = flows_agi.handle(settings, f"run flow {flow.get('name')}")
    # if flow not risky, create one with move
    if "CONFIRM" not in risky.upper():
        risky_flow = flows_engine.save_flow(
            settings,
            {
                "name": "GATE Risky Move",
                "settings": {"source": "altron_chat"},
                "permissions": {"requires_confirm": True},
                "nodes": [
                    {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
                    {
                        "id": "n2",
                        "type": "files.move",
                        "label": "Move",
                        "position": {"x": 200, "y": 0},
                        "config": {"src": str(work / "map_0.txt"), "dst_dir": str(work)},
                    },
                ],
                "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
            },
        )
        risky = flows_agi.handle(settings, f"run flow {risky_flow['name']}")
    confirm_shown = "CONFIRM" in risky.upper()
    pend = safety.pending(settings.safety_path)
    # CANCEL
    mem = JsonlMemory(settings.memory_path)
    tools.run_tool("safety_cancel", "cancel", mem, settings=settings)
    cancelled = safety.pending(settings.safety_path) is None
    # CONFIRM path — hold then confirm a known safe map flow
    safety.request(settings.safety_path, "flow_run", {"flow_id": map_saved["id"]}, "test confirm")
    confirmed = tools.run_tool(
        "safety_confirm",
        "CONFIRM FLOW_RUN",
        mem,
        args={"kind": "flow_run", "payload": {"flow_id": map_saved["id"]}},
        settings=settings,
    )
    confirm_ran = "Flow not found" not in str(confirmed) and len(str(confirmed)) > 10
    gate["SAFETY"] = ok(
        "7 SAFETY confirm+cancel",
        confirm_shown and cancelled and confirm_ran,
        f"shown={confirm_shown} cancel={cancelled} confirm_out={str(confirmed)[:80]}",
    )

    # ---------- 8 TRIGGERS ----------
    # Schedule
    sched = flows_engine.save_flow(
        settings,
        {
            "name": "GATE Schedule",
            "nodes": [
                {"id": "n1", "type": "trigger.schedule", "label": "Sched", "position": {"x": 0, "y": 0}, "config": {"cron": "* * * * *"}},
                {"id": "n2", "type": "logic.log", "label": "L", "position": {"x": 200, "y": 0}, "config": {"message": "sched"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
        },
    )
    srun = flows_runtime.fire_flow(settings, sched["id"], {"source": "trigger.schedule", "cron": "* * * * *", "at": time.time()})
    # File created
    watch = work / "watch"
    watch.mkdir(exist_ok=True)
    fc = flows_engine.save_flow(
        settings,
        {
            "name": "GATE FileCreated",
            "nodes": [
                {"id": "n1", "type": "trigger.file_created", "label": "FC", "position": {"x": 0, "y": 0}, "config": {"path": str(watch)}},
                {"id": "n2", "type": "logic.log", "label": "L", "position": {"x": 200, "y": 0}, "config": {"message": "file={{file.name}}"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
        },
    )
    flows_runtime.tick(settings)  # seed
    probe = watch / f"new_{int(time.time())}.txt"
    probe.write_text("x", encoding="utf-8")
    time.sleep(0.05)
    lines = flows_runtime.tick(settings)
    fc_tick = any(fc["id"] in ln or "file_created" in ln for ln in lines)
    # Webhook
    wh = flows_engine.save_flow(
        settings,
        {
            "name": "GATE Webhook",
            "nodes": [
                {"id": "n1", "type": "trigger.webhook", "label": "WH", "position": {"x": 0, "y": 0}, "config": {"path": "gate-webhook"}},
                {"id": "n2", "type": "logic.log", "label": "L", "position": {"x": 200, "y": 0}, "config": {"message": "wh"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
        },
    )
    whr = flows_runtime.handle_webhook(settings, "gate-webhook", {"ping": True})
    # App started
    ap = flows_engine.save_flow(
        settings,
        {
            "name": "GATE AppStarted",
            "nodes": [
                {"id": "n1", "type": "trigger.app_started", "label": "AS", "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "n2", "type": "logic.log", "label": "L", "position": {"x": 200, "y": 0}, "config": {"message": "boot"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
        },
    )
    flows_runtime._started_once = False  # type: ignore
    as_lines = flows_runtime.run_app_started(settings)
    trig_ok = (
        bool(srun.get("ok"))
        and fc_tick
        and bool(whr.get("ok"))
        and any(ap["id"] in ln for ln in as_lines)
    )
    gate["TRIGGERS"] = ok(
        "8 TRIGGERS real fire",
        trig_ok,
        f"sched={srun.get('status')} fc={lines} wh={whr} app={as_lines}",
    )

    # ---------- 9 RUN HISTORY ----------
    hist = flows_engine.get_run(settings, str(loop_run.get("id")))
    hist_ok = bool(
        hist
        and hist.get("id")
        and hist.get("status")
        and hist.get("nodeResults")
        and hist.get("duration_ms") is not None
        and hist.get("foreach")
    )
    gate["RUN HISTORY"] = ok("9 RUN HISTORY", hist_ok, f"keys={list((hist or {}).keys())[:12]}")

    # ---------- 10 UNDO / VERSION ----------
    v = flows_engine.save_flow(settings, {**e4, "name": "GATE V1"})
    v = flows_engine.save_flow(settings, {**v, "name": "GATE V2"})
    versions = flows_engine.list_versions(settings, v["id"])
    undone = flows_engine.undo_flow(settings, v["id"])
    undo_ok = len(versions) >= 1 and bool(undone) and undone.get("name") == "GATE V1"
    gate["UNDO/VERSIONING"] = ok("10 UNDO/VERSIONING", undo_ok, f"versions={len(versions)} name={(undone or {}).get('name')}")

    # ---------- 11 E2E (chat create organize-style + mapping + safety pieces already) ----------
    e2e = (
        gate.get("NL -> FLOW")
        and gate.get("NL EDIT")
        and gate.get("DATA MAPPING")
        and gate.get("FOREACH")
        and gate.get("IF/ELSE")
        and gate.get("AI AGENT")
        and gate.get("SAFETY")
        and gate.get("TRIGGERS")
        and gate.get("RUN HISTORY")
        and gate.get("UNDO/VERSIONING")
    )
    gate["E2E"] = ok("11 E2E aggregate", e2e)

    # cleanup work files (best effort)
    try:
        for p in work.rglob("*"):
            if p.is_file():
                p.unlink(missing_ok=True)
        for p in sorted(work.rglob("*"), reverse=True):
            if p.is_dir():
                p.rmdir()
        work.rmdir()
    except OSError:
        pass

    print("\n" + "=" * 60)
    print("PHASE 2 GATE REPORT")
    print("=" * 60)
    order = [
        "PHASE 1",
        "NL -> FLOW",
        "NL EDIT",
        "DATA MAPPING",
        "FOREACH",
        "IF/ELSE",
        "AI AGENT",
        "SAFETY",
        "TRIGGERS",
        "RUN HISTORY",
        "UNDO/VERSIONING",
        "E2E",
    ]
    failed = 0
    for k in order:
        v = gate.get(k)
        if v is None:
            print(f"{k}: NOT TESTED")
            failed += 1
        else:
            print(f"{k}: {'PASS' if v else 'FAIL'}")
            if not v:
                failed += 1

    print("-" * 60)
    if failed == 0:
        print("All gate rows PASS — still do NOT auto-declare Phase 2 COMPLETE without manual UI verify.")
        print("PHASE 2 STATUS: GATE PASS (awaiting human verify)")
    else:
        print(f"PHASE 2 STATUS: NOT COMPLETE — {failed} gate row(s) failed")
    print("Phase 3 has NOT been started.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
