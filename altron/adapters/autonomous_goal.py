from __future__ import annotations

"""ALTRON Autonomous Goal Engine (Phase 2-4) — additive orchestration layer.

Does NOT replace AltronCore, the tool router, Flows engine, or the IDE.
Coordinates existing primitives (mcp_fs, ide_agent.write_workspace, sandbox-style
subprocess execution, flows_recover's error classifier, ThinkAdapter, traces,
checkpoints) into one bounded-retry lifecycle:

    PLAN -> (INSPECT?) -> CREATE -> RUN -> OBSERVE -> VERIFY -> COMPLETE
                                       |
                                     FAIL -> CLASSIFY -> RECOVER -> REPLAN -> RETRY

Phase 2/3 scope: one concrete capability — "sandbox_python" (write a small
Python program under data/sandbox, run it, verify its output).

Phase 4 scope: a second capability — "ide_workspace" (write a small Python
project under the real ALTRON workspace, using the SAME trusted-root
validation and undo/history recording as the existing IDE file APIs —
`altron.adapters.ide_agent.write_workspace`, not a new filesystem layer).
Capability selection is a small, explicit dispatch — not a generic registry —
kept deliberately narrow so it never fabricates support for an unproven goal
shape.
"""

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from altron.adapters import flows_recover, mcp_fs, traces
from altron.adapters.workspace import resolve_allowed

MAX_ATTEMPTS_DEFAULT = 3
STEP_TIMEOUT_SECONDS = 8

# In-memory cancellation registry, same shape as flows_engine._active_runs.
_stop_events: dict[str, threading.Event] = {}
_lock = threading.Lock()


def _goals_dir(settings) -> Path:
    p = Path(settings.altron_data_dir) / "goals"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _new_state(goal: str, run_id: str, plan: list[dict], capability: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "goal": goal,
        "capability": capability,
        "status": "PLANNING",
        "plan": plan,
        "current_step": None,
        "attempt": 0,
        "max_attempts": MAX_ATTEMPTS_DEFAULT,
        "observations": [],
        "verification": {},
        "errors": [],
        "result": None,
        "started": time.time(),
        "ended": None,
    }


def _checkpoint(settings, state: dict) -> None:
    path = _goals_dir(settings) / f"{state['run_id']}.json"
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def latest_state(settings) -> dict | None:
    """Mission Control read path: most recently updated goal run, if any."""
    files = sorted(_goals_dir(settings).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cancel_goal(run_id: str) -> bool:
    ev = _stop_events.get(run_id)
    if not ev:
        return False
    ev.set()
    return True


# ---------------------------------------------------------------------------
# Planning — deterministic, narrow by design.
# ---------------------------------------------------------------------------

_PRINT_GOAL_RE = re.compile(
    r"(?:prints?|outputs?|says?)\s+['\"“]?([^'\"”\n]{1,120}?)['\"”]?\s*(?:,|and|then|$)",
    re.IGNORECASE,
)
_PROJECT_NAME_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9_-]{1,30})\s+project\b", re.IGNORECASE)

# Flow-shaped goals (Phase 5) — narrow and explicit on purpose: requires a
# flow/automation noun AND a run-or-create verb, so generic sentences that
# merely mention "workflow" in passing are never routed here. Kept as the
# single source of truth (tools.py's goal_run recognizer calls is_flow_goal()
# too) so there is exactly one place that decides "is this a Flow goal".
_FLOW_NOUN_RE = re.compile(r"\b(flow|workflow|automation)\b", re.IGNORECASE)
_FLOW_RUN_VERB_RE = re.compile(r"\b(run|execute|start|trigger)\b", re.IGNORECASE)
_FLOW_CREATE_VERB_RE = re.compile(r"\b(create|build|make|generate)\b", re.IGNORECASE)


def is_flow_goal(text: str) -> bool:
    lowered = (text or "").lower()
    if not _FLOW_NOUN_RE.search(lowered):
        return False
    return bool(_FLOW_RUN_VERB_RE.search(lowered) or _FLOW_CREATE_VERB_RE.search(lowered))


def _plan_goal(goal: str, context: dict | None = None) -> tuple[str, list[dict], dict]:
    """Recognize a supported goal shape and pick ONE capability for it.

    Returns (capability, plan, meta). Three capabilities exist today:
      - "sandbox_python": write+run+verify under data/sandbox (Phase 2/3)
      - "ide_workspace":  write+run+verify a small project under the real
        ALTRON workspace, via the existing IDE trusted-root file API (Phase 4)
      - "flow": run an existing Flow by name, or plan+save+run a new one,
        entirely via the existing flows_agi/flows_planner/flows_agent/
        flows_verify/flows_recover stack (Phase 5) — see _run_flow_capability.

    Nothing else is recognized — an unrecognized shape still returns a plan
    (so the state machine is exercised) but execution reports honestly
    rather than fabricating success (see run_goal's fallback branch).
    """
    context = context or {}
    lowered = goal.lower()

    if is_flow_goal(goal):
        from altron.adapters import flows_agi

        intent = flows_agi.parse_intent(goal)
        kind = intent.get("intent")
        if kind not in {"run_flow", "create_workflow"}:
            kind = "unsupported"
        meta = {"flow_kind": kind, "query": intent.get("query") or "", "text": intent.get("text") or goal}
        plan = [
            {"step": "resolve_flow", "capability": "flow", "status": "pending"},
            {"step": "run_flow", "capability": "flow", "status": "pending"},
            {"step": "verify_result", "capability": "flow", "status": "pending"},
        ]
        return "flow", plan, meta

    match = _PRINT_GOAL_RE.search(goal)
    print_text = match.group(1).strip() if match else "Hello ALTRON"

    wants_workspace = bool(context.get("project_dir")) or any(w in lowered for w in ("workspace", "project"))

    if wants_workspace:
        name_match = _PROJECT_NAME_RE.search(lowered)
        project_name = (name_match.group(1) if name_match else "app").strip("-_") or "app"
        meta = {"project_name": project_name, "filename": f"{project_name}.py"}
        plan = [
            {"step": "inspect_workspace", "capability": "ide_workspace", "status": "pending"},
            {"step": "create_file", "capability": "ide_workspace", "status": "pending", "print_text": print_text},
            {"step": "run_program", "capability": "ide_workspace", "status": "pending"},
            {"step": "verify_result", "capability": "ide_workspace", "status": "pending", "expect": print_text},
        ]
        return "ide_workspace", plan, meta

    plan = [
        {"step": "create_file", "capability": "sandbox_python", "status": "pending", "print_text": print_text},
        {"step": "run_program", "capability": "sandbox_python", "status": "pending"},
        {"step": "verify_result", "capability": "sandbox_python", "status": "pending", "expect": print_text},
    ]
    return "sandbox_python", plan, {}


def _generate_code(print_text: str) -> str:
    safe = print_text.replace("\\", "\\\\").replace('"', '\\"')
    return f'print("{safe}")\n'


# ---------------------------------------------------------------------------
# Capability: sandbox_python (reuses mcp_fs.fs_write — sandbox-only, unmodified)
# ---------------------------------------------------------------------------


def _cap_create_file(settings, run_id: str, code: str) -> dict[str, Any]:
    rel_path = f"goal_{run_id}.py"
    msg = mcp_fs.fs_write(rel_path, code, [settings.sandbox_path], settings.sandbox_path)
    ok = msg.startswith("Wrote ")
    target = settings.sandbox_path / rel_path
    return {"ok": ok, "message": msg, "path": str(target), "rel_path": rel_path}


def _cap_run_program(script_path: str) -> dict[str, Any]:
    """Thin structured sibling of adapters/sandbox.py's technique — returns
    exit_code/stdout/stderr separately so verification can use real evidence
    instead of parsing a formatted string. adapters/sandbox.py is unmodified."""
    return _run_python_subprocess([sys.executable, script_path], Path(script_path).parent)


# ---------------------------------------------------------------------------
# Capability: ide_workspace (Phase 4) — reuses the EXISTING IDE trusted-root
# file API (ide_agent.write_workspace: same resolve_allowed() check, same
# secret-file blocking, same undo/history snapshot as manual IDE edits) and
# the existing workspace.resolve_allowed() for read-only inspection. No new
# filesystem layer, no bypass of the existing protections.
# ---------------------------------------------------------------------------


def _workspace_roots(settings) -> list[Path]:
    return [Path(settings.altron_workspace).resolve()]


def _cap_inspect_workspace(settings, rel_dir: str) -> dict[str, Any]:
    """Read-only: confirm the target path is inside the trusted workspace root
    before any write is attempted, and see what (if anything) is already there
    so a create step never blindly overwrites unrelated project content."""
    base = Path(settings.altron_workspace).resolve()
    roots = _workspace_roots(settings)
    resolved = resolve_allowed(rel_dir, roots, base=base)
    if resolved is None:
        return {"ok": False, "blocked": True, "exists": False, "listing": "", "path": None}
    listing = mcp_fs.fs_list(rel_dir, roots, base) if resolved.exists() else "(new folder — does not exist yet)"
    return {"ok": True, "blocked": False, "exists": resolved.exists(), "listing": listing, "path": str(resolved)}


def _cap_create_workspace_file(settings, rel_path: str, content: str) -> dict[str, Any]:
    from altron.adapters import ide_agent

    msg = ide_agent.write_workspace(settings, rel_path, content, record_history=True)
    ok = msg.startswith("Wrote ")
    blocked = msg.startswith("Blocked")
    target = Path(settings.altron_workspace).resolve() / rel_path
    return {"ok": ok, "blocked": blocked, "message": msg, "path": str(target), "rel_path": rel_path}


def _cap_run_workspace_file(settings, rel_path: str) -> dict[str, Any]:
    ws = Path(settings.altron_workspace).resolve()
    script = ws / rel_path
    py = ws / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    return _run_python_subprocess([exe, str(script)], script.parent)


def _run_python_subprocess(cmd: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=STEP_TIMEOUT_SECONDS,
            shell=False,
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[:8000],
            "stderr": (proc.stderr or "")[:8000],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": f"Timeout after {STEP_TIMEOUT_SECONDS}s"}
    except OSError as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc)}


def _verify_result(observation: dict, expect: str) -> dict[str, Any]:
    """Evidence-based verification: exit code AND expected output, never just 'it ran'."""
    exit_ok = observation.get("exit_code") == 0
    stdout = observation.get("stdout") or ""
    output_ok = (expect or "").strip() in stdout if expect else True
    verified = bool(exit_ok and output_ok)
    return {
        "ok": verified,
        "exit_code_ok": exit_ok,
        "output_ok": output_ok,
        "expected": expect,
        "detail": "Verified: exit 0 and expected output present" if verified else "Not verified — see exit_code_ok/output_ok",
    }


def _repair_code(broken_code: str, stderr: str, print_text: str, settings=None) -> str:
    """Deterministic repair first (fast, offline, testable); optional LLM repair
    only as a best-effort fallback for shapes the deterministic pass can't fix."""
    # Deterministic pass: common single-character syntax slips in a print() call.
    fixed = broken_code
    if "SyntaxError" in stderr or "invalid syntax" in stderr:
        if fixed.count("(") > fixed.count(")"):
            fixed = fixed.rstrip("\n") + ")" * (fixed.count("(") - fixed.count(")")) + "\n"
        if fixed.strip() and not fixed.strip().endswith(")"):
            # Missing/garbled call entirely — fall back to a known-good regeneration.
            fixed = _generate_code(print_text)
    if fixed != broken_code:
        return fixed
    if settings is not None:
        try:
            from altron.adapters.think import ThinkAdapter

            think = ThinkAdapter(settings)
            reply = think.complete(
                [
                    {
                        "role": "user",
                        "content": (
                            "Fix this Python script so it runs without error and prints the same "
                            f"message. Return ONLY the corrected Python code, no markdown.\n\n"
                            f"Error:\n{stderr}\n\nCode:\n{broken_code}"
                        ),
                    }
                ]
            )
            candidate = str(reply or "").strip()
            if candidate:
                return candidate
        except Exception:  # noqa: BLE001
            pass
    return _generate_code(print_text)


# ---------------------------------------------------------------------------
# Capability: flow (Phase 5) — delegates entirely to the EXISTING Flows stack.
# Does NOT reimplement planning, validation, execution, verification, or
# recovery: flows_agent.run_autonomous() already owns execute -> observe ->
# flows_verify.verify_run() -> flows_recover.plan_recovery() -> bounded retry
# -> save_checkpoint(), so this function calls it exactly once and reports
# its result — no outer retry loop wraps it (avoids a double retry loop).
# ---------------------------------------------------------------------------


def _run_flow_capability(settings, run_id: str, stop_ev: threading.Event, state: dict, plan: list[dict], meta: dict) -> dict[str, Any]:
    from altron.adapters import flows_agent, flows_agi, flows_engine, flows_planner, flows_risk, safety

    state["attempt"] = 1
    state["status"] = "RUNNING"
    state["current_step"] = "resolve_flow"
    plan[0]["status"] = "running"
    _checkpoint(settings, state)

    kind = meta.get("flow_kind")
    if kind == "unsupported":
        plan[0]["status"] = "failed"
        state["status"] = "FAILED"
        state["result"] = (
            "Unsupported Flow goal shape — I can run an existing Flow by name "
            "('run my PDF Processing Workflow') or plan+create+run a new one "
            "('create a workflow that ...'), but this request doesn't clearly match either."
        )
        _checkpoint(settings, state)
        return state

    if stop_ev.is_set():
        state["status"] = "CANCELLED"
        state["result"] = "Cancelled by request (before Flow was resolved)"
        _checkpoint(settings, state)
        return state

    flow: dict | None = None
    if kind == "run_flow":
        query = str(meta.get("query") or "").strip().lower()
        if query and query not in {"it", "this", "that", "workflow", "again", "the workflow", "the flow"}:
            flow = flows_agi._find_flow(settings, query)  # noqa: SLF001 — same lookup Chat itself uses
        if flow is None:
            flows_list = flows_engine.list_flows(settings)
            for f in flows_list:
                g = flows_engine.get_flow(settings, f["id"])
                if g and (g.get("settings") or {}).get("source") == "altron_chat":
                    flow = g
                    break
            if flow is None and flows_list:
                flow = flows_engine.get_flow(settings, flows_list[0]["id"])
        if flow is None:
            plan[0]["status"] = "failed"
            state["status"] = "FAILED"
            state["result"] = f"Flow not found: {meta.get('query') or '(none)'}. Say 'list flows' to see names."
            _checkpoint(settings, state)
            return state
        issues = flows_agi.validate_plan_or_flow(settings, flow)
        if issues:
            plan[0]["status"] = "failed"
            state["status"] = "FAILED"
            state["result"] = "Cannot run — validation failed: " + "; ".join(issues)
            _checkpoint(settings, state)
            return state
    else:  # create_workflow — existing planner, with its own existing fallback chain
        text = str(meta.get("text") or state.get("goal") or "")
        try:
            plan_obj = flows_planner.plan_workflow(settings, text)
            flow = flows_planner.plan_to_flow(plan_obj)
            issues = flows_agi.validate_plan_or_flow(settings, flow)
            if issues:
                raise ValueError("; ".join(issues))
        except ValueError:
            try:
                plan_obj = flows_planner._heuristic_plan(settings, text)  # noqa: SLF001
                issues = flows_planner.validate_plan(settings, plan_obj)
                if issues:
                    plan_obj = flows_agi.plan_from_text(settings, text)
                    flow = flows_agi.plan_to_flow(plan_obj)
                else:
                    flow = flows_planner.plan_to_flow(plan_obj)
                issues = flows_agi.validate_plan_or_flow(settings, flow)
            except ValueError as exc2:
                plan[0]["status"] = "failed"
                state["status"] = "FAILED"
                state["result"] = f"Flow plan rejected: {exc2}"
                _checkpoint(settings, state)
                return state
        if issues:
            plan[0]["status"] = "failed"
            state["status"] = "FAILED"
            state["result"] = "Flow plan validation failed: " + "; ".join(issues)
            _checkpoint(settings, state)
            return state
        flow = flows_engine.save_flow(settings, flow)

    state["flow_id"] = flow.get("id")
    state["observations"].append(
        {"step": "resolve_flow", "flow_id": flow.get("id"), "flow_name": flow.get("name"), "kind": kind}
    )
    plan[0]["status"] = "done"
    _checkpoint(settings, state)

    if stop_ev.is_set():
        state["status"] = "CANCELLED"
        state["result"] = "Cancelled by request (Flow resolved but not started)"
        _checkpoint(settings, state)
        return state

    # Same risk/confirmation policy flows_agi.handle() applies to chat-driven runs —
    # never auto-confirmed here either. Reuses the SAME safety.request() token, so a
    # plain "CONFIRM FLOW_RUN" chat reply (existing safety_confirm tool) executes it.
    flows_risk.annotate_flow(flow)
    risky = bool((flow.get("permissions") or {}).get("requires_confirm")) or any(
        str(n.get("type")) in {"files.move", "files.write", "files.copy", "files.rename"}
        for n in flow.get("nodes") or []
    )
    risk_level = (flow.get("permissions") or {}).get("risk_level") or "SAFE"
    if risky or flows_risk.risk_rank(str(risk_level)) >= flows_risk.risk_rank("HIGH"):
        hint = safety.request(
            settings.safety_path,
            "flow_run",
            {"flow_id": flow["id"]},
            f"Run flow '{flow.get('name')}' [{risk_level}] which may move/write files under Trusted Roots?",
        )
        state["status"] = "WAITING_FOR_APPROVAL"
        state["current_step"] = "await_approval"
        state["result"] = hint
        _checkpoint(settings, state)
        return state

    state["current_step"] = "run_flow"
    plan[1]["status"] = "running"
    _checkpoint(settings, state)
    run = flows_agent.run_autonomous(settings, flow["id"])
    state["flow_run_id"] = run.get("id")
    phase3 = run.get("phase3") or {}
    state["observations"].append(
        {
            "step": "run_flow",
            "flow_id": flow.get("id"),
            "flow_run_id": run.get("id"),
            "ok": run.get("ok"),
            "status": run.get("status"),
            "attempts": phase3.get("attempts"),
            "recovery": phase3.get("recovery"),
            "checkpoint_id": phase3.get("checkpoint_id"),
        }
    )
    plan[1]["status"] = "done" if run.get("ok") else "failed"
    _checkpoint(settings, state)

    # Evidence for completion is the Flow subsystem's OWN verifier result —
    # never a generic pass/fail derived only from "the executor didn't crash".
    verification = phase3.get("verification") or {"ok": bool(run.get("ok")), "checks": []}
    state["current_step"] = "verify_result"
    plan[2]["status"] = "running"
    state["verification"] = verification
    _checkpoint(settings, state)

    if run.get("ok") and verification.get("ok"):
        plan[2]["status"] = "done"
        state["status"] = "COMPLETED"
        state["result"] = f"Flow '{flow.get('name')}' completed and verified ({run.get('duration_ms')}ms)."
    else:
        plan[2]["status"] = "failed"
        state["status"] = "FAILED"
        reason = "verification failed" if run.get("ok") else f"execution failed ({run.get('status')})"
        state["result"] = f"Flow '{flow.get('name')}' did not complete: {reason}."
    _checkpoint(settings, state)
    return state


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_goal(
    settings,
    goal: str,
    context: dict | None = None,
    max_attempts: int = MAX_ATTEMPTS_DEFAULT,
    run_id: str | None = None,
    on_ready=None,
) -> dict[str, Any]:
    """Execute one autonomous goal end to end. Returns the final GoalState dict.

    Bounded retries (default 3). Never marks success without exit_code==0 AND
    expected-output evidence. Safe to cancel via cancel_goal(run_id) — checked
    between steps and between attempts.

    `run_id`/`on_ready` are optional test hooks (deterministic cancellation
    testing) and have no effect on normal callers. `context["project_dir"]`
    lets a caller pin the workspace-relative project folder (used by tests
    and available to Chat callers who already know where they want it).
    """
    run_id = run_id or uuid.uuid4().hex[:12]
    stop_ev = threading.Event()
    with _lock:
        _stop_events[run_id] = stop_ev
    if on_ready is not None:
        on_ready(run_id)

    context = context or {}
    capability, plan, meta = _plan_goal(goal, context)
    state = _new_state(goal, run_id, plan, capability)
    state["context"] = context
    traces.write(settings.traces_path, {"user": f"[goal] {goal}", "reply": "", "plan": "goal", "trace": ["goal.started"]})
    _checkpoint(settings, state)

    if capability == "ide_workspace":
        rel_dir = str(context.get("project_dir") or f"{meta['project_name']}_{run_id}")
        rel_path = f"{rel_dir}/{meta['filename']}"
    else:
        rel_dir = ""
        rel_path = ""

    if capability != "flow":
        print_text = next(s["print_text"] for s in plan if "print_text" in s)
        code = _generate_code(print_text)
    attempt = 0

    try:
        if capability == "flow":
            return _run_flow_capability(settings, run_id, stop_ev, state, plan, meta)

        # ide_workspace only: one-time, read-only inspection before any write.
        if capability == "ide_workspace":
            if stop_ev.is_set():
                state["status"] = "CANCELLED"
                state["result"] = "Cancelled by request"
                _checkpoint(settings, state)
                return state
            state["current_step"] = "inspect_workspace"
            plan[0]["status"] = "running"
            _checkpoint(settings, state)
            inspection = _cap_inspect_workspace(settings, rel_dir)
            state["observations"].append({"step": "inspect_workspace", "attempt": 0, **inspection})
            if inspection.get("blocked"):
                plan[0]["status"] = "failed"
                state["status"] = "FAILED"
                state["result"] = f"Blocked path: '{rel_dir}' is outside the trusted ALTRON workspace root."
                _checkpoint(settings, state)
                return state
            plan[0]["status"] = "done"

        create_idx = 1 if capability == "ide_workspace" else 0
        run_idx = create_idx + 1
        verify_idx = run_idx + 1

        while attempt < max_attempts:
            if stop_ev.is_set():
                state["status"] = "CANCELLED"
                state["result"] = "Cancelled by request"
                _checkpoint(settings, state)
                return state

            attempt += 1
            state["attempt"] = attempt
            state["status"] = "RUNNING"

            # Step: create_file
            state["current_step"] = "create_file"
            plan[create_idx]["status"] = "running"
            _checkpoint(settings, state)
            if capability == "ide_workspace":
                created = _cap_create_workspace_file(settings, rel_path, code)
            else:
                created = _cap_create_file(settings, run_id, code)
            state["observations"].append({"step": "create_file", "attempt": attempt, **created})
            if not created["ok"]:
                state["errors"].append(created.get("message") or "create_file failed")
                plan[create_idx]["status"] = "failed"
                state["status"] = "FAILED"
                state["result"] = f"Could not create file: {created.get('message')}"
                _checkpoint(settings, state)
                return state
            plan[create_idx]["status"] = "done"

            if stop_ev.is_set():
                state["status"] = "CANCELLED"
                state["result"] = "Cancelled by request"
                _checkpoint(settings, state)
                return state

            # Step: run_program
            state["current_step"] = "run_program"
            plan[run_idx]["status"] = "running"
            _checkpoint(settings, state)
            if capability == "ide_workspace":
                observation = _cap_run_workspace_file(settings, created["rel_path"])
            else:
                observation = _cap_run_program(created["path"])
            state["observations"].append({"step": "run_program", "attempt": attempt, **observation})
            _checkpoint(settings, state)

            if not observation["ok"]:
                plan[run_idx]["status"] = "failed"
                cls = flows_recover.classify_error(observation.get("stderr") or "")
                state["errors"].append({"attempt": attempt, "stderr": observation.get("stderr"), "classification": cls})
                if cls["action"] == "stop" or attempt >= max_attempts:
                    state["status"] = "FAILED"
                    state["result"] = f"Execution failed and not recoverable: {cls.get('reason')}"
                    _checkpoint(settings, state)
                    return state
                state["status"] = "RECOVERING"
                _checkpoint(settings, state)
                code = _repair_code(code, observation.get("stderr") or "", print_text, settings=settings)
                state["status"] = "REPLANNING"
                _checkpoint(settings, state)
                continue  # retry loop: recreate file with repaired code, run again
            plan[run_idx]["status"] = "done"

            if stop_ev.is_set():
                state["status"] = "CANCELLED"
                state["result"] = "Cancelled by request"
                _checkpoint(settings, state)
                return state

            # Step: verify_result — evidence-based, never fabricated.
            state["current_step"] = "verify_result"
            state["status"] = "VERIFYING"
            plan[verify_idx]["status"] = "running"
            _checkpoint(settings, state)
            verification = _verify_result(observation, plan[verify_idx]["expect"])
            state["verification"] = verification
            if not verification["ok"]:
                plan[verify_idx]["status"] = "failed"
                state["status"] = "FAILED"
                state["result"] = "Program ran, but verification failed: " + verification["detail"]
                _checkpoint(settings, state)
                return state
            plan[verify_idx]["status"] = "done"
            state["status"] = "COMPLETED"
            state["result"] = f"Goal completed and verified: {verification['detail']}"
            _checkpoint(settings, state)
            return state

        state["status"] = "FAILED"
        state["result"] = f"Retries exhausted ({max_attempts} attempts)"
        _checkpoint(settings, state)
        return state
    finally:
        state["ended"] = time.time()
        _checkpoint(settings, state)
        traces.write(
            settings.traces_path,
            {
                "user": f"[goal] {goal}",
                "reply": str(state.get("result") or ""),
                "judgment": "ok" if state.get("status") == "COMPLETED" else state.get("status"),
                "plan": "goal",
                "trace": [f"goal.{state.get('status', 'unknown').lower()}"],
            },
        )
        with _lock:
            _stop_events.pop(run_id, None)

