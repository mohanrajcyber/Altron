from __future__ import annotations

"""Phase 3 tests — planner, agent loop, recovery, verify, risk, context, editor helpers.

Uses real temporary files under Trusted Roots. No fake success.
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from altron.adapters import (
    flows_agent,
    flows_agi,
    flows_context,
    flows_engine,
    flows_planner,
    flows_recover,
    flows_risk,
    flows_verify,
    pc_roots,
    safety,
)
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


def make_scan_flow(settings, folder: str, name: str) -> dict:
    plan = flows_planner.plan_workflow(
        settings,
        f"Create a workflow that scans {folder} for PDF files and logs the results.",
    )
    flow = flows_planner.plan_to_flow(plan)
    flow["name"] = name
    return flows_engine.save_flow(settings, flow)


def main() -> int:
    settings = get_settings()
    failed = 0
    desktop = root_named(settings, "Desktop")
    work = Path(desktop) / f"_altron_p3_{int(time.time())}"
    work.mkdir(exist_ok=True)
    print(f"P3 workdir: {work}")

    # 1 simple NL -> Flow
    out = flows_agi.handle(settings, "Create a workflow that scans Downloads for PDF files and logs the results.")
    m = re.search(r"\((flow_[a-f0-9]+|[a-f0-9]{8,})\)", out)
    flow1 = flows_engine.get_flow(settings, m.group(1)) if m else None
    failed += not ok("1 simple NL->Flow", bool(flow1) and "Created workflow" in out, out[:120])

    # 2 complex multi-step NL -> Flow
    out2 = flows_agi.handle(
        settings,
        "Create a workflow that scans Downloads for PDFs, analyzes them with AI, renames and moves them to Documents.",
    )
    m2 = re.search(r"\((flow_[a-f0-9]+|[a-f0-9]{8,})\)", out2)
    flow2 = flows_engine.get_flow(settings, m2.group(1)) if m2 else None
    types2 = [n.get("type") for n in (flow2 or {}).get("nodes") or []]
    has_scan = "files.list" in types2 or "trigger.file_created" in types2
    complex_ok = (
        flow2 is not None
        and has_scan
        and any(str(t).startswith("ai.") for t in types2)
        and ("files.move" in types2 or "files.rename" in types2)
    )
    failed += not ok("2 complex NL->Flow", complex_ok, f"types={types2}")

    # 3 planner validation + explanation
    plan = flows_planner.plan_workflow(settings, "Scan Downloads for PDFs and log results")
    issues = flows_planner.validate_plan(settings, plan)
    failed += not ok("3 planner validation", not issues, str(issues))
    failed += not ok("3b plan explanation", bool(plan.get("explanation")), str(plan.get("explanation"))[:80])

    # 4 dynamic node selection (catalog only)
    allowed = set(flows_planner.catalog_types())
    bad = [t for t in [n.get("type") for n in plan.get("nodes") or []] if t not in allowed]
    failed += not ok("4 dynamic catalog-only", not bad, str(bad))

    # 5 risk classification
    risk = flows_risk.classify_flow(flow2 or {"nodes": []})
    failed += not ok(
        "5 risk HIGH for move/rename",
        flows_risk.risk_rank(risk.get("risk_level")) >= flows_risk.risk_rank("HIGH"),
        str(risk),
    )

    # 6 context / variables
    scan = make_scan_flow(settings, "Desktop", f"P3 Scan {work.name}")
    # point list node at work dir
    for n in scan.get("nodes") or []:
        if n.get("type") == "files.list":
            n.setdefault("config", {})["path"] = str(work)
            n["config"]["pattern"] = "*.txt"
    scan = flows_engine.save_flow(settings, scan)
    (work / "a.txt").write_text("hello-p3", encoding="utf-8")
    run = flows_agent.run_autonomous(settings, scan["id"], max_attempts=1)
    ctx = flows_context.build_context(settings, user_command="scan", flow=scan, run=run)
    flows_context.persist_context(settings, scan["id"], ctx)
    loaded = flows_context.load_context(settings, scan["id"])
    failed += not ok("5b context persist", bool(loaded and loaded.get("flow", {}).get("id") == scan["id"]))
    failed += not ok("6 autonomous success", bool(run.get("ok")), f"status={run.get('status')}")
    failed += not ok("6b phase3 meta", bool((run.get("phase3") or {}).get("autonomous")), str(run.get("phase3")))
    failed += not ok(
        "6c verification pass",
        bool((run.get("phase3") or {}).get("verification", {}).get("ok")),
        str((run.get("phase3") or {}).get("verification")),
    )

    # 7 retry classification
    cls = flows_recover.classify_error("AI JSON schema validation failed")
    failed += not ok("7 retryable class", cls.get("action") == "retry", str(cls))

    # 8 recoverable failure plan
    fake_run = {
        "ok": False,
        "status": "FAILED",
        "nodeResults": [{"nodeId": "nX", "label": "AI", "status": "FAILED", "error": "connection timed out"}],
    }
    plan_r = flows_recover.plan_recovery(fake_run, attempt=0)
    failed += not ok("8 recoverable retry plan", plan_r.get("action") == "retry", str(plan_r))

    # 9 unrecoverable
    plan_u = flows_recover.plan_recovery(
        {
            "ok": False,
            "nodeResults": [{"nodeId": "nY", "label": "X", "status": "FAILED", "error": "path not in trusted roots"}],
        },
        attempt=0,
    )
    failed += not ok("9 unrecoverable stop", plan_u.get("action") == "stop", str(plan_u))

    # 10 checkpoint / resume
    ckpt_id = (run.get("phase3") or {}).get("checkpoint_id") or ""
    ckpt = flows_agent.load_checkpoint(settings, ckpt_id) if ckpt_id else None
    failed += not ok("10 checkpoint saved", bool(ckpt), str(ckpt_id))
    resumed = flows_agent.run_autonomous(settings, scan["id"], max_attempts=1, resume_checkpoint=ckpt_id or "missing")
    failed += not ok("10b resume re-executes", "phase3" in resumed, str(resumed.get("status")))

    # 11 verification failure (fake missing dest after claimed move success)
    vfail = flows_verify.verify_run(
        settings,
        {
            "nodes": [{"id": "m1", "type": "files.move", "config": {}}],
        },
        {
            "ok": True,
            "status": "SUCCESS",
            "nodeResults": [
                {
                    "nodeId": "m1",
                    "status": "SUCCESS",
                    "output": {"path": str(work / "does_not_exist_p3.bin")},
                }
            ],
        },
    )
    failed += not ok("11 verification failure detected", not vfail.get("ok"), str(vfail))

    # 12 safety confirmation for risky flow
    if flow2:
        out_run = flows_agi.handle(settings, f"run flow {flow2.get('name')}")
        needs = "confirm" in out_run.lower() or "trusted" in out_run.lower() or "approve" in out_run.lower()
        failed += not ok("12 safety confirmation", needs, out_run[:160])
    else:
        failed += not ok("12 safety confirmation", False, "no flow2")

    # 13 destructive cancellation — deny pending safety
    msg = safety.request(
        settings.safety_path,
        "flow_run",
        {"flow_id": scan["id"]},
        "P3 test confirm?",
    )
    pending = "confirm" in msg.lower() or "safety hold" in msg.lower()
    safety.clear(settings.safety_path)
    cancelled = safety.pending(settings.safety_path) is None
    failed += not ok("13 destructive cancellation path", pending and cancelled, msg[:120])

    # 14 dynamic workflow E2E filesystem
    dest = work / "out.txt"
    if dest.exists():
        dest.unlink()
    write_flow = {
        "id": "flow_p3_write_" + str(int(time.time())),
        "name": "P3 Write Verify",
        "nodes": [
            {"id": "t1", "type": "trigger.manual", "label": "Manual", "config": {}, "position": {"x": 40, "y": 80}},
            {
                "id": "w1",
                "type": "files.write",
                "label": "Write",
                "config": {"path": str(dest), "content": "phase3-ok"},
                "position": {"x": 280, "y": 80},
            },
            {"id": "l1", "type": "logic.log", "label": "Log", "config": {"message": "wrote"}, "position": {"x": 520, "y": 80}},
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "w1", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "w1", "target": "l1", "sourceHandle": "default", "targetHandle": "in"},
        ],
        "permissions": {"requires_confirm": False},
        "settings": {"source": "altron_chat", "phase": 3},
    }
    write_flow = flows_risk.annotate_flow(write_flow)
    # HIGH risk write still runnable via engine/agent directly (chat would confirm)
    write_flow = flows_engine.save_flow(settings, write_flow)
    wr = flows_agent.run_autonomous(settings, write_flow["id"], max_attempts=1)
    failed += not ok("14 write E2E", bool(wr.get("ok")) and dest.is_file() and dest.read_text(encoding="utf-8") == "phase3-ok")
    failed += not ok(
        "14b verify write",
        bool((wr.get("phase3") or {}).get("verification", {}).get("ok")),
        str((wr.get("phase3") or {}).get("verification")),
    )

    # 15 run-history recovery trace
    # Force a retryable failure by pointing list at missing path inside trusted root name but nonexistent
    bad_path = Path(desktop) / f"_missing_p3_{int(time.time())}"
    bad_flow = make_scan_flow(settings, "Desktop", "P3 Bad Path")
    for n in bad_flow.get("nodes") or []:
        if n.get("type") == "files.list":
            n.setdefault("config", {})["path"] = str(bad_path)
    bad_flow = flows_engine.save_flow(settings, bad_flow)
    br = flows_agent.run_autonomous(settings, bad_flow["id"], max_attempts=2)
    p3 = br.get("phase3") or {}
    failed += not ok(
        "15 recovery trace",
        bool(p3.get("recovery")) and bool(p3.get("timeline")),
        f"recovery={p3.get('recovery')} final_ok={br.get('ok')}",
    )

    # 16 editor multi-select/keyboard — static presence checks in flows.js
    js = (ROOT / "altron" / "web" / "flows.js").read_text(encoding="utf-8")
    editor_ok = all(
        s in js
        for s in (
            "selectedIds",
            "copySelectedNodes",
            "pasteClipboard",
            "autoLayout",
            'key === "z"',
            "duplicateSelectedNodes",
        )
    )
    failed += not ok("16 editor multi-select/keyboard", editor_ok)

    # risk annotate on save path
    failed += not ok("risk levels defined", flows_risk.RISK_ORDER[0] == "SAFE" and flows_risk.RISK_ORDER[-1] == "DESTRUCTIVE")

    print("\n" + ("PHASE3 TESTS PASS" if failed == 0 else f"PHASE3 TESTS FAIL count={failed}"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
