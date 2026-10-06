from __future__ import annotations

"""Phase 1 automated checks for ALTRON FLOWS chat control + engine pieces."""

import json
import sys
from pathlib import Path

# Allow running as script from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from altron.adapters import flows_agi, flows_engine, flows_expr, tools
from altron.settings import get_settings


def ok(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    settings = get_settings()
    failed = 0

    # A. Intent parsing
    intent = flows_agi.parse_intent("create a workflow that scans Downloads for PDF files and logs the results")
    failed += not ok("A intent create", intent.get("intent") == "create_workflow")
    intent = flows_agi.parse_intent("list flows")
    failed += not ok("A intent list", intent.get("intent") == "list_flows")
    intent = flows_agi.parse_intent("Delete everything from C:\\")
    failed += not ok("A intent deny", intent.get("intent") == "deny")

    # B/E expressions
    ctx = {"variables": {"list.count": 5, "filter.count": 2}, "last_listing": [{"name": "a.pdf"}], "file": {"extension": "pdf"}}
    failed += not ok("E expr count>0", flows_expr.evaluate_bool("count > 0", ctx) is True)
    failed += not ok("E expr count==5", flows_expr.evaluate_bool("list.count == 5", ctx) is True)
    failed += not ok("E expr contains", flows_expr.evaluate_bool("contains .pdf", ctx) is True)
    failed += not ok("E expr and", flows_expr.evaluate_bool("list.count > 1 and filter.count > 0", ctx) is True)

    # C create + run (no AI for speed)
    plan = flows_agi.plan_from_text(settings, "create a workflow that scans Desktop and logs all files")
    flow = flows_agi.plan_to_flow(plan)
    issues = flows_agi.validate_plan_or_flow(settings, flow)
    failed += not ok("C plan validate", not issues, str(issues))
    saved = flows_engine.save_flow(settings, flow)
    run = flows_engine.run_flow(settings, saved["id"])
    failed += not ok("C run ok", bool(run.get("ok")), run.get("status"))
    failed += not ok("C has logs", len(run.get("logs") or []) > 2)

    # D variables present
    failed += not ok("D variables", bool(run.get("variables")), str(list((run.get("variables") or {}).keys())[:5]))

    # F If/Else via engine demo
    run2 = flows_engine.run_flow(settings, "demo_if_branch")
    last = {}
    for r in run2.get("nodeResults") or []:
        last[r["nodeId"]] = r["status"]
    # n4 yes, n5 no — one success one not in results as success for skipped
    failed += not ok("F if branch yes", last.get("n4") == "SUCCESS", str(last))

    # G Loop foreach small
    desktop = ""
    from altron.adapters import pc_roots

    for r in pc_roots.list_roots(settings):
        if r["name"].lower() == "desktop":
            desktop = r["path"]
            break
    loop_flow = {
        "name": "Phase1 Loop Test",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "files.list", "label": "L", "position": {"x": 200, "y": 0}, "config": {"path": desktop}},
            {"id": "n3", "type": "logic.filter", "label": "F", "position": {"x": 400, "y": 0}, "config": {"pattern": ".lnk"}},
            {"id": "n4", "type": "logic.foreach", "label": "Each", "position": {"x": 600, "y": 0}, "config": {"max": "3"}},
            {"id": "n5", "type": "logic.log", "label": "ItemLog", "position": {"x": 800, "y": 0}, "config": {"message": "item={{item.name}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e4", "source": "n4", "target": "n5", "sourceHandle": "default", "targetHandle": "in"},
        ],
    }
    saved_loop = flows_engine.save_flow(settings, loop_flow)
    run_loop = flows_engine.run_flow(settings, saved_loop["id"])
    item_logs = [r for r in (run_loop.get("nodeResults") or []) if r.get("nodeId") == "n5" and r.get("status") == "SUCCESS"]
    failed += not ok("G foreach iterations", len(item_logs) >= 1, f"iters={len(item_logs)} ok={run_loop.get('ok')}")

    # I permission denial
    deny = flows_agi.handle(settings, "Delete everything from C:\\")
    failed += not ok("I deny destructive", "Denied" in deny or "denied" in deny.lower(), deny[:80])

    # K save/reload
    got = flows_engine.get_flow(settings, saved["id"])
    failed += not ok("K reload", bool(got and got.get("nodes")), saved["id"])

    # L run history
    runs = flows_engine.recent_runs(settings, limit=3)
    failed += not ok("L history", len(runs) >= 1)

    # Chat tool routing
    picked = tools.pick_action("list flows", settings)
    failed += not ok("Chat pick list", picked and picked[0] == "flows_act", str(picked))
    picked2 = tools.pick_action("open flows", settings)
    failed += not ok("Chat pick open", picked2 and picked2[0] == "flows_open", str(picked2))

    # NL create via handle (no confirm path)
    out = flows_agi.handle(settings, "create a workflow that scans Desktop and logs the results")
    failed += not ok("NL create", "Created workflow" in out, out[:120])

    print("\nRESULT:", "ALL PASS" if failed == 0 else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
