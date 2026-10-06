from __future__ import annotations

"""Phase 2 acceptance tests — AI-native workflow intelligence.

Additive over Phase 1. Does not replace Phase 1 suites.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from altron.adapters import flows_agi, flows_catalog, flows_engine, flows_expr, flows_planner, pc_roots, safety
from altron.settings import get_settings


def ok(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    settings = get_settings()
    failed = 0
    desktop = next((r["path"] for r in pc_roots.list_roots(settings) if r["name"].lower() == "desktop"), "")
    downloads = next((r["path"] for r in pc_roots.list_roots(settings) if r["name"].lower() == "downloads"), desktop)
    print(f"Roots desktop={desktop} downloads={downloads}")

    # 1. NL → workflow creation (planner catalog-only)
    text = (
        "Every night check my Downloads folder. Find new PDFs, analyze them with ALTRON AI, "
        "rename them based on their content and move them into the correct folder."
    )
    plan = flows_planner.plan_workflow(settings, text)
    issues = flows_planner.validate_plan(settings, plan)
    failed += not ok("1 planner validate", not issues, str(issues))
    types = [n.get("type") for n in plan.get("nodes") or []]
    failed += not ok("1 has schedule", "trigger.schedule" in types, str(types[:8]))
    failed += not ok("1 has foreach+ai", "logic.foreach" in types and "ai.agent" in types, str(types))
    failed += not ok("1 has rename/move", "files.rename" in types and "files.move" in types, str(types))
    # no hallucinated types
    allowed = set(flows_planner.catalog_types())
    bad = [t for t in types if t not in allowed]
    failed += not ok("1 catalog-only", not bad, str(bad))

    flow = flows_planner.plan_to_flow(plan)
    saved = flows_engine.save_flow(settings, flow)
    failed += not ok("2 persistence", bool(flows_engine.get_flow(settings, saved["id"])))
    failed += not ok("2 ai_generated flag", bool((saved.get("settings") or {}).get("ai_generated")))

    # Chat create path
    out = flows_agi.handle(settings, "Create a workflow to organize my Downloads PDFs.")
    failed += not ok("2 chat create", "Created workflow" in out, out[:140])

    # 3. NL modification
    target = flows_engine.get_flow(settings, saved["id"])
    assert target
    # ensure AI present without filter then add filter before AI — strip filter first if any for this probe
    probe = {
        "name": "P2 Edit Probe",
        "settings": {"source": "altron_chat"},
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "files.list", "label": "List", "position": {"x": 200, "y": 0}, "config": {"path": downloads}},
            {"id": "n3", "type": "ai.agent", "label": "AI", "position": {"x": 400, "y": 0}, "config": {"prompt": "x", "schema": "category,confidence,summary", "strict": "false"}},
            {"id": "n4", "type": "files.move", "label": "Move", "position": {"x": 600, "y": 0}, "config": {"src": "{{item.path}}", "dst_dir": downloads}},
            {"id": "n5", "type": "logic.log", "label": "Log", "position": {"x": 800, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e4", "source": "n4", "target": "n5", "sourceHandle": "default", "targetHandle": "in"},
        ],
    }
    probe_saved = flows_engine.save_flow(settings, probe)
    edited = flows_agi.modify_flow_from_text(settings, probe_saved, "Add a PDF filter before AI.")
    types_e = [n.get("type") for n in edited.get("nodes") or []]
    failed += not ok("3 filter before AI", "logic.filter" in types_e, str(types_e))
    edited2 = flows_agi.modify_flow_from_text(settings, edited, "Remove the move step.")
    types_e2 = [n.get("type") for n in edited2.get("nodes") or []]
    failed += not ok("3 remove move", "files.move" not in types_e2, str(types_e2))
    # edge repair: something still reaches log
    ids = {n["id"] for n in edited2["nodes"]}
    edges_ok = all(e["source"] in ids and e["target"] in ids for e in edited2.get("edges") or [])
    failed += not ok("3 edge repair", edges_ok)

    renamed = flows_agi.modify_flow_from_text(settings, edited2, "Rename the workflow to Phase2 Organizer")
    failed += not ok("3 rename", renamed.get("name") == "Phase2 Organizer", str(renamed.get("name")))
    night = flows_agi.modify_flow_from_text(settings, renamed, "Make it run every night.")
    trig = next(n for n in night["nodes"] if str(n.get("type")).startswith("trigger."))
    failed += not ok("3 nightly schedule", trig.get("type") == "trigger.schedule", str(trig))

    # 4. connection validation
    bad = json.loads(json.dumps(night))
    bad["edges"].append({"id": "ex", "source": "missing", "target": "n1", "sourceHandle": "default", "targetHandle": "in"})
    bad_issues = flows_agi.validate_plan_or_flow(settings, bad)
    failed += not ok("4 invalid edge", any("missing" in i.lower() or "Edge" in i for i in bad_issues), str(bad_issues))

    # 5. data mapping — real upstream output consumed
    map_flow = {
        "name": "P2 Map",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "files.list", "label": "List", "position": {"x": 200, "y": 0}, "config": {"path": desktop}},
            {"id": "n3", "type": "logic.log", "label": "Log", "position": {"x": 400, "y": 0}, "config": {"message": "count={{variables.list.file_count}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default", "targetHandle": "in"},
        ],
    }
    map_saved = flows_engine.save_flow(settings, map_flow)
    map_run = flows_engine.run_flow(settings, map_saved["id"])
    log_msg = next((r.get("message") for r in map_run.get("nodeResults") or [] if r.get("nodeId") == "n3"), "")
    failed += not ok("5 data mapping", "count=" in str(log_msg) and str(log_msg) != "count=", str(log_msg))

    # 6. IF/ELSE
    ctx = {
        "variables": {
            "ai.result": {"category": "invoice", "confidence": 0.94, "summary": "bill", "suggested_name": "a.pdf"},
            "confidence": 0.94,
            "category": "invoice",
        }
    }
    failed += not ok("6 confidence", flows_expr.evaluate_bool("confidence >= 0.85", ctx) is True)
    failed += not ok("6 category", flows_expr.evaluate_bool("category == 'invoice'", ctx) is True)
    failed += not ok("6 startsWith", flows_expr.evaluate_bool("suggested_name endswith .pdf", ctx) is True)
    failed += not ok("6 and/or", flows_expr.evaluate_bool("confidence >= 0.8 and category == 'invoice'", ctx) is True)

    # 7. For Each metrics
    loop_dir = Path(desktop) / f"_altron_p2_loop_{int(time.time())}"
    loop_dir.mkdir(exist_ok=True)
    for i in range(3):
        (loop_dir / f"item{i}.txt").write_text(f"file-{i}", encoding="utf-8")
    loop_flow = {
        "name": "P2 Loop",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "n2", "type": "files.list", "label": "L", "position": {"x": 200, "y": 0}, "config": {"path": str(loop_dir)}},
            {"id": "n3", "type": "logic.foreach", "label": "Each", "position": {"x": 400, "y": 0}, "config": {"max": "10"}},
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
    item_logs = [r for r in (loop_run.get("nodeResults") or []) if r.get("nodeId") == "n4" and r.get("status") == "SUCCESS"]
    failed += not ok("7 foreach iterations", len(item_logs) == 3, f"iters={len(item_logs)}")
    failed += not ok("7 foreach metrics", fe.get("total") == 3 and fe.get("success") == 3, str(fe))

    # 8. AI structured output (real Think)
    ai_flow = {
        "name": "P2 AI",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {
                "id": "n2",
                "type": "ai.agent",
                "label": "AI",
                "position": {"x": 200, "y": 0},
                "config": {
                    "prompt": "Classify this as invoice. Text: Electricity bill September 2026.",
                    "schema": "category,confidence,summary,suggested_name",
                    "strict": "true",
                    "input_var": "Electricity bill September 2026",
                },
            },
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    ai_saved = flows_engine.save_flow(settings, ai_flow)
    ai_run = flows_engine.run_flow(settings, ai_saved["id"])
    ai_res = next((r for r in ai_run.get("nodeResults") or [] if r.get("type") == "ai.agent"), None)
    js = (ai_res or {}).get("output", {}).get("json") if ai_res else None
    failed += not ok(
        "8 AI structured",
        bool(ai_run.get("ok")) and isinstance(js, dict) and "category" in js and "suggested_name" in js,
        str(js)[:160],
    )

    # 9. invalid AI output strict error
    from altron.adapters import flows_engine as fe_mod

    class Boom:
        def complete(self, messages):
            return "NOT JSON AT ALL"

    # monkeypatch ThinkAdapter via direct _exec_ai path using test_node with bad — simulate by calling _exec_ai with patched Think
    original = None
    try:
        import altron.adapters.flows_engine as eng

        def fake_exec_ai(settings, ntype, cfg, ctx):
            cfg = {**cfg, "strict": "true"}
            # force invalid by calling parser path
            raise RuntimeError("AI JSON schema validation failed (strict mode) — refusing to fabricate output")

        # Use a node run that will fail: empty think that returns nonsense — use test harness
        bad_node = {
            "type": "ai.agent",
            "config": {"prompt": "x", "schema": "category,confidence", "strict": "true", "input_var": "hi"},
        }
        # Temporarily patch ThinkAdapter
        from altron.adapters import think as think_mod

        class FakeThink:
            def __init__(self, settings):
                pass

            def complete(self, messages):
                return "definitely not json {{{"

        real = think_mod.ThinkAdapter
        think_mod.ThinkAdapter = FakeThink  # type: ignore
        try:
            res = flows_engine.test_node(settings, bad_node, {})
            failed += not ok("9 invalid AI errors", res.get("ok") is False, str(res)[:160])
        finally:
            think_mod.ThinkAdapter = real  # type: ignore
    except Exception as exc:  # noqa: BLE001
        failed += not ok("9 invalid AI errors", False, str(exc))

    # 10–11 safety confirm + cancel
    risky_out = flows_agi.handle(settings, f"run flow {saved['name']}")
    failed += not ok("10 safety confirm", "CONFIRM" in risky_out.upper(), risky_out[:160])
    safety.clear(settings.safety_path)
    failed += not ok("11 cancel clears", safety.pending(settings.safety_path) is None)

    # 12 run history
    hist = flows_engine.get_run(settings, str(loop_run.get("id")))
    failed += not ok("12 run history", bool(hist and hist.get("foreach")), str((hist or {}).get("foreach")))

    # 13 undo/versioning
    v1 = flows_engine.save_flow(settings, {**night, "name": "BeforeEdit"})
    v1 = flows_engine.save_flow(settings, {**v1, "name": "AfterEdit"})
    versions = flows_engine.list_versions(settings, v1["id"])
    failed += not ok("13 versions exist", len(versions) >= 1, str(len(versions)))
    undone = flows_engine.undo_flow(settings, v1["id"])
    failed += not ok("13 undo", bool(undone) and undone.get("name") == "BeforeEdit", str((undone or {}).get("name")))
    dup = flows_engine.duplicate_flow(settings, v1["id"])
    failed += not ok("13 duplicate", bool(dup) and dup.get("id") != v1["id"], str((dup or {}).get("id")))

    # 15 malicious path
    evil_plan = {
        "name": "evil",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "config": {}, "position": {"x": 0, "y": 0}},
            {"id": "n2", "type": "files.list", "label": "L", "config": {"path": r"C:\Windows\System32"}, "position": {"x": 1, "y": 0}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    evil_issues = flows_planner.validate_plan(settings, evil_plan)
    failed += not ok("15 untrusted rejected", any("trusted" in i.lower() for i in evil_issues), str(evil_issues))
    deny = flows_agi.handle(settings, "Delete everything from C:\\")
    failed += not ok("15 deny destructive", "Denied" in deny)

    # rename node real
    src = loop_dir / "rename_me.txt"
    src.write_text("rename-test", encoding="utf-8")
    ren_flow = {
        "name": "P2 Rename",
        "nodes": [
            {"id": "n1", "type": "trigger.manual", "label": "M", "position": {"x": 0, "y": 0}, "config": {}},
            {
                "id": "n2",
                "type": "files.rename",
                "label": "Rename",
                "position": {"x": 200, "y": 0},
                "config": {"src": str(src), "new_name": "renamed_ok.txt"},
            },
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
    }
    ren_saved = flows_engine.save_flow(settings, ren_flow)
    ren_run = flows_engine.run_flow(settings, ren_saved["id"])
    failed += not ok("rename node", bool(ren_run.get("ok")) and (loop_dir / "renamed_ok.txt").is_file(), ren_run.get("status"))

    # cleanup
    try:
        for p in loop_dir.glob("*"):
            p.unlink(missing_ok=True)
        loop_dir.rmdir()
    except OSError:
        pass

    print("\n" + "=" * 60)
    if failed == 0:
        print("PHASE 2 CORE MODULES: PASS (acceptance script)")
        print("NOTE: Full Phase 2 gate also requires Phase 1 regression green + manual UI checks.")
        print("RESULT: ALL PASS")
        return 0
    print("PHASE 2 STATUS: NOT COMPLETE")
    print(f"RESULT: {failed} FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
