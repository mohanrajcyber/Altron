from __future__ import annotations

"""FORGE orchestration over ALTRON's existing IDE agent and workspace guards."""

import ast
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from altron.adapters import ide_agi, ide_agent
from altron.adapters.workspace import resolve_allowed

_BUILD_VERB = re.compile(r"\b(create|build|make|develop|generate|scaffold)\b", re.I)
_BUILD_NOUN = re.compile(
    r"\b(project|application|app|tool|scanner|dashboard|website|web\s*app|"
    r"api|service|utility|program|script|analyzer|monitor|interface|ui)\b",
    re.I,
)
_SKIP_CONTEXT_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def is_build_request(text: str) -> bool:
    """Route explicit project-creation requests, but not Flows or explanations."""
    value = (text or "").strip()
    lowered = value.lower()
    if not value or re.search(r"\b(flow|workflow|automation)\b", lowered):
        return False
    if re.search(r"\b(explain|describe|how does)\b", lowered):
        return False
    return bool(_BUILD_VERB.search(value) and _BUILD_NOUN.search(value))


def classify_request(text: str) -> str:
    if is_build_request(text):
        return "BUILD_PROJECT"
    from altron.adapters.autonomous_goal import is_flow_goal

    if is_flow_goal(text):
        return "FLOW"
    return "CHAT"


def _project_slug(text: str) -> str:
    match = re.search(
        r"\b(?:create|build|make|develop|generate|scaffold)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?(.+)",
        text,
        re.I,
    )
    phrase = match.group(1) if match else "altron-project"
    phrase = re.split(r"\b(?:with|using|for|that|which)\b|[,;]", phrase, maxsplit=1, flags=re.I)[0]
    ignored = {"python", "javascript", "typescript", "with", "clean", "simple", "a", "an", "the"}
    words = [word.lower() for word in re.findall(r"[A-Za-z0-9]+", phrase) if word.lower() not in ignored]
    slug = "-".join(words[:4]).strip("-") or "altron-project"
    return slug[:48].strip("-") or "altron-project"


def _available_project_dir(settings, slug: str) -> str:
    root = Path(settings.altron_workspace).resolve()
    candidate = f"forge_projects/{slug}"
    suffix = 2
    while True:
        resolved = resolve_allowed(candidate, [root], base=root)
        if resolved is None or not resolved.exists():
            return candidate
        candidate = f"forge_projects/{slug}-{suffix}"
        suffix += 1


def _emit(progress, event: str, **details) -> None:
    if progress:
        progress({"event": event, "at": time.time(), **details})


def _confirmed_project_files(settings, project_dir: str) -> list[str]:
    root = Path(settings.altron_workspace).resolve()
    directory = resolve_allowed(project_dir, [root], base=root)
    if directory is None or not directory.is_dir():
        return []
    confirmed: list[str] = []
    for candidate in sorted(directory.rglob("*")):
        if not candidate.is_file() or any(part.startswith(".") or part in _SKIP_CONTEXT_DIRS for part in candidate.relative_to(directory).parts):
            continue
        rel_path = candidate.relative_to(root).as_posix()
        resolved = resolve_allowed(rel_path, [root], base=root)
        if resolved is not None and resolved.is_file():
            confirmed.append(resolved.relative_to(root).as_posix())
    return confirmed


def run_build(settings, core, command: str, plan_only: bool = False, progress=None) -> dict[str, Any]:
    """Build through the current IDE agent, then verify its reported files."""
    if not is_build_request(command):
        return {"ok": False, "status": "REJECTED", "error": "This is not a project build request."}

    base_slug = _project_slug(command)
    folder = f"forge_projects/{base_slug}" if plan_only else _available_project_dir(settings, base_slug)
    _emit(progress, "request_accepted", project_dir=folder)
    if plan_only:
        agent = ide_agi.run_turn(
            settings=settings,
            core=core,
            message=command.strip(),
            mode="PLAN",
            force_plan=True,
        )
        return {
            "ok": True,
            "status": "PLANNED",
            "command": command,
            "project_dir": folder,
            "files": [],
            "validations": [],
            "errors": [],
            "reply": agent.get("reply") or "",
            "trace": agent.get("trace") or [],
        }

    root = Path(settings.altron_workspace).resolve()
    created_dir = ide_agent.create_path(settings, folder, "dir")
    if not created_dir.startswith("Created dir:"):
        return {
            "ok": False,
            "status": "FAILED",
            "command": command,
            "project_dir": folder,
            "files": [],
            "validations": [],
            "errors": [created_dir],
            "reply": "Could not initialize a new project folder.",
            "trace": [],
        }
    _emit(progress, "workspace_created", project_dir=folder)

    instruction = f"{command.strip()}\n\nCreate every new project file inside `{folder}` only."
    if re.search(r"\b(port\s*scan|port\s*scanner|cybersecurity|network\s*scan)\b", command, re.I):
        instruction += (
            " For this educational cybersecurity project, only permit scanning 127.0.0.1/localhost; "
            "reject every other target. Do not add stealth, evasion, exploitation, or public-network scanning."
        )
    _emit(progress, "generation_started", project_dir=folder)
    agent = ide_agi.run_turn(
        settings=settings,
        core=core,
        message=instruction,
        mode="EDIT",
        project_root=folder,
        on_progress=lambda event: _emit(progress, "file_written", **event),
    )
    reported = agent.get("created") or []
    reported_paths: list[str] = []
    errors: list[str] = []
    roots = [root]

    for raw_path in reported:
        rel_path = ide_agi._project_write_path(str(raw_path), folder)
        if rel_path is None:
            errors.append(f"Blocked or invalid reported path: {raw_path}")
            continue
        resolved = resolve_allowed(rel_path, roots, base=root)
        if resolved is None or not resolved.is_file():
            errors.append(f"Not found or blocked: {rel_path}")
            continue
        reported_paths.append(resolved.relative_to(root).as_posix())

    verified_paths = _confirmed_project_files(settings, folder)
    if not verified_paths and reported_paths:
        errors.append("Agent reported files, but no project files were found on disk.")

    python_files = [path for path in verified_paths if path.lower().endswith(".py")]
    _emit(progress, "validation_started", files=len(verified_paths))
    syntax_errors: list[str] = []
    for rel_path in python_files:
        source, error = ide_agent.read_bytes(settings, rel_path)
        if source is None:
            syntax_errors.append(f"{rel_path}: {error or 'could not read file'}")
            continue
        try:
            ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            syntax_errors.append(f"{rel_path}:{exc.lineno}: {exc.msg}")

    syntax_ok = bool(python_files) and not syntax_errors
    validations = [
        {"name": "Project files", "status": "PASSED" if verified_paths else "FAILED", "detail": f"{len(verified_paths)} file(s) confirmed on disk"},
        {
            "name": "Python syntax",
            "status": ("PASSED" if syntax_ok else "FAILED") if python_files else "NOT APPLICABLE",
            "detail": "; ".join(syntax_errors) if syntax_errors else (f"{len(python_files)} file(s) parsed" if python_files else "No Python files generated"),
        },
        {"name": "Tests", "status": "NOT RUN", "detail": "Generated project code was not executed automatically."},
        {
            "name": "Security review",
            "status": "NOT RUN",
            "detail": "Generated source was not security-audited; review it before running.",
        },
    ]
    ok = bool(verified_paths) and not errors and (not python_files or syntax_ok)
    _emit(
        progress,
        "validation_finished",
        status="PASSED" if ok else "FAILED",
        files=len(verified_paths),
        errors=len(errors) + len(syntax_errors),
    )
    return {
        "ok": ok,
        "status": "COMPLETED" if ok else "FAILED",
        "command": command,
        "project_dir": folder,
        "files": verified_paths,
        "validations": validations,
        "errors": errors + syntax_errors,
        "reply": agent.get("reply") or "",
        "trace": agent.get("trace") or [],
    }


def start_build_job(settings, core, command: str) -> dict[str, Any]:
    if not is_build_request(command):
        return {"ok": False, "error": "This is not a project build request."}
    run_id = uuid.uuid4().hex
    state: dict[str, Any] = {
        "id": run_id,
        "status": "RUNNING",
        "command": command,
        "events": [],
        "result": None,
        "started": time.time(),
    }
    with _jobs_lock:
        _jobs[run_id] = state
        for old_id, old in sorted(_jobs.items(), key=lambda item: item[1]["started"])[:-20]:
            if old["status"] != "RUNNING":
                _jobs.pop(old_id, None)

    def report(event: dict[str, Any]) -> None:
        with _jobs_lock:
            current = _jobs.get(run_id)
            if current is not None:
                current["events"].append(event)

    def worker() -> None:
        try:
            result = run_build(settings, core, command, progress=report)
            with _jobs_lock:
                current = _jobs.get(run_id)
                if current is not None:
                    current["result"] = result
                    current["status"] = result.get("status", "FAILED")
                    current["ended"] = time.time()
                    current["events"].append(
                        {"event": "build_finished", "at": current["ended"], "status": current["status"]}
                    )
        except Exception as exc:  # noqa: BLE001
            with _jobs_lock:
                current = _jobs.get(run_id)
                if current is not None:
                    current["status"] = "FAILED"
                    current["error"] = str(exc)
                    current["ended"] = time.time()
                    current["events"].append(
                        {"event": "build_failed", "at": current["ended"], "detail": str(exc)}
                    )

    threading.Thread(target=worker, name=f"forge-{run_id[:8]}", daemon=True).start()
    return {"ok": True, "id": run_id}


def build_job(run_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        state = _jobs.get(run_id)
        return dict(state) if state is not None else None


def explain_project(settings, core, project_dir: str, question: str) -> dict[str, Any]:
    """Explain bounded, current files from one Forge project through the IDE agent."""
    requested = (project_dir or "").replace("\\", "/").strip("/")
    if not requested.startswith("forge_projects/"):
        return {"ok": False, "error": "Project context must be inside forge_projects/."}

    root = Path(settings.altron_workspace).resolve()
    directory = resolve_allowed(requested, [root], base=root)
    if directory is None or not directory.is_dir():
        return {"ok": False, "error": "Forge project folder was not found in the trusted workspace."}

    context_files: list[str] = []
    total_chars = 0
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or set(path.parts) & _SKIP_CONTEXT_DIRS or any(part.startswith(".") for part in path.relative_to(directory).parts):
            continue
        resolved = resolve_allowed(path.relative_to(root).as_posix(), [root], base=root)
        if resolved is None:
            continue
        content, error = ide_agent.read_bytes(settings, resolved.relative_to(root).as_posix())
        if content is None or error:
            continue
        remaining = 48_000 - total_chars
        if remaining <= 0 or len(context_files) >= 16:
            break
        content = content[:remaining]
        rel_path = resolved.relative_to(root).as_posix()
        context_files.append(f"File: {rel_path}\n```\n{content}\n```")
        total_chars += len(content)

    if not context_files:
        return {"ok": False, "error": "No readable project files were found to explain."}

    prompt = (
        f"{(question or 'Explain what you created.').strip()}\n\n"
        "Explain only behavior supported by the actual project files below. If something is missing or unverified, say so. "
        "Cover purpose, architecture, important files, validation, how to run it, and relevant security limits. "
        "Do not claim that code or tests were executed unless the supplied evidence says they were.\n\n"
        + "\n\n".join(context_files)
    )
    result = ide_agi.run_turn(settings=settings, core=core, message=prompt, mode="ASK")
    return {"ok": True, "reply": result.get("reply") or "", "files": [item.split("\n", 1)[0][6:] for item in context_files]}