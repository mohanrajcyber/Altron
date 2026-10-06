from __future__ import annotations

"""Phase 3 — post-execution verification for ALTRON FLOWS."""

from pathlib import Path
from typing import Any

from altron.adapters import pc_roots


def verify_run(settings, flow: dict, run: dict) -> dict[str, Any]:
    """Verify expected outcomes after a run. Never fabricates success."""
    checks: list[dict] = []
    nodes = {n["id"]: n for n in (flow.get("nodes") or []) if n.get("id")}
    results = {r.get("nodeId"): r for r in (run.get("nodeResults") or []) if r.get("nodeId")}

    # Terminal status check
    status = str(run.get("status") or "")
    checks.append(
        {
            "name": "terminal_status",
            "ok": status in {"SUCCESS", "FAILED", "CANCELLED"},
            "detail": f"status={status}",
        }
    )

    for nid, node in nodes.items():
        ntype = str(node.get("type") or "")
        res = results.get(nid) or {}
        st = res.get("status")
        if st == "SKIPPED":
            continue
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}

        if ntype == "files.move" and st == "SUCCESS":
            out = res.get("output") if isinstance(res.get("output"), dict) else {}
            dest = out.get("path") or ""
            exists = bool(dest) and Path(str(dest)).is_file()
            checks.append({"name": f"move_exists:{nid}", "ok": exists, "detail": str(dest)})

        if ntype == "files.rename" and st == "SUCCESS":
            out = res.get("output") if isinstance(res.get("output"), dict) else {}
            dest = out.get("path") or ""
            exists = bool(dest) and Path(str(dest)).is_file()
            checks.append({"name": f"rename_exists:{nid}", "ok": exists, "detail": str(dest)})

        if ntype == "files.write" and st == "SUCCESS":
            out = res.get("output") if isinstance(res.get("output"), dict) else {}
            dest = out.get("path") or ""
            exists = bool(dest) and Path(str(dest)).is_file()
            checks.append({"name": f"write_exists:{nid}", "ok": exists, "detail": str(dest)})

        if ntype == "files.list" and st == "SUCCESS":
            out = res.get("output") if isinstance(res.get("output"), dict) else {}
            folder = out.get("path") or cfg.get("path") or ""
            resolved = pc_roots.resolve_in_roots(settings, str(folder)) if folder else None
            checks.append(
                {
                    "name": f"list_folder:{nid}",
                    "ok": resolved is not None and resolved.is_dir(),
                    "detail": str(folder),
                }
            )

        if ntype.startswith("ai.") and st == "SUCCESS":
            out = res.get("output") if isinstance(res.get("output"), dict) else {}
            js = out.get("json")
            schema_ok = bool(out.get("schema_ok")) or isinstance(js, dict)
            checks.append({"name": f"ai_schema:{nid}", "ok": schema_ok, "detail": str(type(js).__name__)})

        if ntype == "logic.foreach" and st == "SUCCESS":
            fe = res.get("foreach") or run.get("foreach") or {}
            total = int(fe.get("total") or 0)
            success = int(fe.get("success") or 0)
            failed = int(fe.get("failed") or 0)
            checks.append(
                {
                    "name": f"foreach_metrics:{nid}",
                    "ok": total == success + failed + int(fe.get("skipped") or 0),
                    "detail": f"total={total} success={success} failed={failed}",
                }
            )

        if st == "FAILED":
            checks.append(
                {
                    "name": f"node_failed:{nid}",
                    "ok": False,
                    "detail": str(res.get("error") or res.get("message") or "FAILED"),
                }
            )

    ok = all(c.get("ok") for c in checks) if checks else bool(run.get("ok"))
    # If run failed, verification overall is false even if some checks pass
    if not run.get("ok"):
        ok = False
    return {"ok": ok, "checks": checks, "at": run.get("ended")}
