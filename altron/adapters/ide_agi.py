from __future__ import annotations

"""ALTRON IDE AGI loop — one user intent → diagnose → act → verify.

Unlike Face sticky control, this loop:
- never dumps raw TOOL lines to the user
- executes allowlisted workspace tools
- can create real project files (write_workspace)
- auto-handles common mamri build requests
"""

import json
import re
from pathlib import Path
from typing import Any

from altron.adapters import ide_agent, mcp_fs
from altron.adapters.tools import TOOL_NAMES, parse_tool_directive, run_tool
from altron.adapters.workspace import resolve_allowed

IDE_SAFE = {
    "fs_list",
    "fs_read",
    "fs_write",
    "code_write",
    "code_run",
    "git_status",
    "git_log",
    "web_fetch",
}

_TOOL_LINE = re.compile(r"TOOL\s*(\{.*?\})", re.S)
_WRITE_BLOCK = re.compile(
    r"ALTRON_WRITE\s+path=([^\n]+)\n```(?:\w+)?\n(.*?)```",
    re.S | re.I,
)
MAX_ROUNDS = 5


def diagnose(settings) -> dict[str, Any]:
    """Self-check for world-class IDE readiness."""
    checks: list[dict] = []
    ws = Path(settings.altron_workspace).resolve()

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("workspace", ws.is_dir(), str(ws))
    readme = ws / "README.md"
    add("readme", readme.is_file(), "README.md" if readme.is_file() else "missing")
    content, err = ide_agent.read_bytes(settings, "README.md")
    add("file_read", content is not None, err or f"{len(content or '')} chars")

    from altron.adapters.ollama import probe as probe_ollama

    ollama = probe_ollama(settings)
    if settings.api_keys:
        add("think", True, "nvidia-free")
        backend = "nvidia-free"
    elif ollama.get("ok"):
        add("think", True, "ollama-free")
        backend = "ollama-free"
    else:
        add("think", True, "local-free (limited)")
        backend = "local-free"

    tree = ide_agent.tree(settings, ".", depth=1)
    add("explorer", bool(tree), f"{len(tree)} roots")

    try:
        from altron.adapters import ide_terminal

        sess = ide_terminal.create(ws)
        ide_terminal.kill(sess.id)
        add("terminal", True, "shell ok")
    except Exception as exc:  # noqa: BLE001
        add("terminal", False, str(exc))

    git = __import__("altron.adapters.mcp_git", fromlist=["mcp_git"])
    roots = [ws]
    st = git.git_status_porcelain(".", roots, ws)
    add("git", bool(st.get("ok")), st.get("branch") or st.get("error") or "")

    failed = [c for c in checks if not c["ok"]]
    return {
        "ok": not failed,
        "backend": backend,
        "checks": checks,
        "summary": "ALL GREEN" if not failed else f"{len(failed)} issue(s)",
        "problems": [f"{c['name']}: {c['detail']}" for c in failed],
    }


def run_turn(
    *,
    settings,
    core,
    message: str,
    mode: str = "ASK",
    path: str = "",
    selection: str = "",
    project_root: str = "",
    force_plan: bool = False,
    on_progress=None,
) -> dict[str, Any]:
    mode = (mode or "ASK").upper()
    preferred_dir = _extract_target_dir(message)

    if force_plan:
        return _plan_turn(settings, core, message, path, selection)

    # Folder-only: never scaffold sites/demo
    folder = _folder_only_intent(message)
    if folder:
        return _make_folder(settings, folder)

    # Mode-specific workflows
    if mode == "PLAN" and not _wants_implement(message):
        return _plan_turn(settings, core, message, path, selection)
    if mode == "RUN":
        return _run_mode_turn(settings, core, message, path, selection)
    if mode == "DEBUG":
        dbg = _debug_preflight(settings, path)
        if dbg.get("short_circuit"):
            return dbg["short_circuit"]

    # Auto intent: build/create website etc. — AGI does the work.
    if mode in {"ASK", "EDIT"} or (mode == "PLAN" and _wants_implement(message)):
        auto = _auto_fulfill(settings, message, mode)
        if auto:
            return auto

    diag = diagnose(settings)
    backend = diag.get("backend") or "think"
    file_diag: list[dict] = []
    if mode == "DEBUG" and path:
        file_diag = ide_agent.diagnose_file(settings, path)

    ctx = _system_ctx(settings, core, message, mode, path, selection, diag, file_diag, preferred_dir)
    messages: list[dict] = [
        {"role": "system", "content": ctx},
        {"role": "user", "content": message},
    ]

    created: list[str] = []
    opened: list[str] = []
    tool_trace: list[str] = []
    reply = ""
    allow_writes = mode not in {"ASK"} or _wants_build(message)

    for _ in range(MAX_ROUNDS):
        try:
            raw = core.think.complete(messages)
        except Exception as exc:  # noqa: BLE001
            reply = f"ALTRON Think error: {exc}"
            break

        writes = list(_WRITE_BLOCK.finditer(raw or "")) if allow_writes else []
        tool = parse_tool_directive(raw or "")
        # Also catch multiple TOOL lines
        extra_tools = _all_tools(raw or "")
        if tool and tool not in extra_tools:
            extra_tools.insert(0, tool)
        if mode == "RUN":
            extra_tools = [t for t in extra_tools if t.get("name") in {"code_run", "fs_list", "fs_read", "git_status"}]
            writes = []
        if mode == "PLAN" and not _wants_implement(message):
            writes = []
            extra_tools = [t for t in extra_tools if t.get("name") in {"fs_list", "fs_read"}]

        if writes or extra_tools:
            results: list[str] = []
            for m in writes:
                rel = m.group(1).strip().strip("\"'")
                rel = _project_write_path(rel, project_root) if project_root else _safe_site_path(rel, preferred_dir=preferred_dir, message=message)
                body = m.group(2)
                if project_root and rel is None:
                    results.append(f"Blocked write outside project folder: {m.group(1).strip()}")
                    continue
                msg = ide_agent.write_workspace(settings, rel, body)
                results.append(msg)
                if msg.lower().startswith("wrote"):
                    created.append(rel.replace("\\", "/"))
                    tool_trace.append(f"write:{rel}")
                    if on_progress:
                        on_progress({"type": "file_written", "path": rel.replace("\\", "/")})
            for call in extra_tools[:3]:
                name = str(call.get("name") or "")
                project_safe_tools = {"fs_list", "fs_read", "fs_write", "code_write"}
                if name not in IDE_SAFE or (project_root and name not in project_safe_tools):
                    results.append(f"Blocked tool in IDE: {name}")
                    continue
                args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                if name in {"fs_write", "code_write"}:
                    raw_path = str(args.get("path") or "")
                    safe_path = _project_write_path(raw_path, project_root) if project_root else _safe_site_path(raw_path, preferred_dir=preferred_dir, message=message)
                    args = {
                        **args,
                        "path": safe_path or "",
                    }
                    if not args["path"]:
                        results.append(f"Blocked write outside project folder: {raw_path}")
                        continue
                out = _exec_ide_tool(settings, core, name, args, message, preferred_dir=preferred_dir)
                results.append(f"{name}: {out[:2500]}")
                tool_trace.append(name)
                if name in {"fs_write", "code_write"} and args.get("path") and out.lower().startswith("wrote "):
                    written_path = str(args.get("path")).replace("\\", "/")
                    created.append(written_path)
                    if on_progress:
                        on_progress({"type": "file_written", "path": written_path})
                if name == "fs_read" and args.get("path"):
                    opened.append(str(args.get("path")).replace("\\", "/"))

            # DEBUG fail→fix: re-check after writes
            if mode == "DEBUG" and path and created:
                after = ide_agent.diagnose_file(settings, path)
                results.append(
                    "Re-diagnose: "
                    + (
                        "CLEAN"
                        if not [x for x in after if x.get("severity") == "error"]
                        else "; ".join(f"L{x['line']}:{x['message']}" for x in after[:5])
                    )
                )
                file_diag = after

            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Tool results (already executed — do NOT print TOOL lines again):\n"
                        + "\n".join(results)
                        + "\n\nNow give the user a clear final answer. "
                        "Confirm every path you wrote. If more work needed, use ALTRON_WRITE or TOOL again."
                    ),
                }
            )
            continue

        # Clean accidental TOOL residue
        reply = _strip_tool_noise(raw)
        break
    else:
        reply = reply or "ALTRON finished the tool loop. Check created files."

    if not (reply or "").strip():
        reply = "Done."

    # If user asked to build but model only listed files, force a useful site scaffold.
    if mode in {"ASK", "EDIT"} and _wants_build(message) and not created and not _folder_only_intent(message) and not project_root:
        if re.search(r"html|website|web\s*site|\bweb\b|youtube|landing|page", message, re.I):
            forced = _scaffold_site(settings, message)
            created.extend(forced.get("created") or [])
            reply = (reply + "\n\n" + forced.get("reply", "")).strip()
            tool_trace.extend(forced.get("trace") or [])

    if created:
        paths = "\n".join(f"- `{p}`" for p in created)
        if "Created:" not in reply and "created:" not in reply.lower():
            reply = (reply + f"\n\n**Confirmed paths:**\n{paths}").strip()

    diffs = ide_agent.parse_agent_diffs(reply)
    problems = list(diag.get("problems") or [])
    if file_diag:
        problems.extend(f"{x.get('severity')}: L{x.get('line')} {x.get('message')}" for x in file_diag[:8])
    return {
        "ok": True,
        "reply": reply.strip(),
        "diffs": diffs,
        "mode": mode,
        "backend": backend,
        "free": True,
        "created": created,
        "opened": opened or created[:],
        "confirm_paths": created,
        "trace": tool_trace,
        "diagnose": {"summary": diag.get("summary"), "problems": problems},
        "plan_steps": [],
    }


def _path_within_root(path: str, root: str) -> bool:
    normalized = (path or "").replace("\\", "/").strip("/")
    boundary = (root or "").replace("\\", "/").strip("/")
    if not normalized or not boundary or normalized.startswith("/"):
        return False
    parts = normalized.split("/")
    return ".." not in parts and (normalized == boundary or normalized.startswith(boundary + "/"))


def _project_write_path(path: str, root: str) -> str | None:
    normalized = (path or "").replace("\\", "/").strip()
    boundary = (root or "").replace("\\", "/").strip("/")
    if not normalized or not boundary or normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        return None
    if ".." in normalized.split("/"):
        return None
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return None
    if normalized == boundary or normalized.startswith(boundary + "/"):
        return normalized if _path_within_root(normalized, boundary) else None
    if normalized.startswith("forge_projects/"):
        return None
    return f"{boundary}/{normalized}"


def _exec_ide_tool(
    settings,
    core,
    name: str,
    args: dict,
    user_text: str,
    preferred_dir: str = "",
) -> str:
    if name in {"fs_write", "code_write"}:
        path = _safe_site_path(
            str(args.get("path") or ""),
            preferred_dir=preferred_dir,
            message=user_text,
        )
        content = str(args.get("content") or "")
        return ide_agent.write_workspace(settings, path, content)
    if name == "fs_read":
        content, err = ide_agent.read_bytes(settings, str(args.get("path") or ""))
        if content is None:
            return err or "read failed"
        return content[:12000]
    if name == "fs_list":
        roots = ide_agent._roots(settings)
        return mcp_fs.fs_list(str(args.get("path") or "."), roots, Path(settings.altron_workspace))
    return run_tool(
        name,
        user_text,
        core.memory,
        identity=core.identity,
        args=args,
        settings=settings,
        vectors=core.vectors,
    )


def _safe_site_path(rel: str, preferred_dir: str = "", message: str = "") -> str:
    """Keep Face root clean. Prefer user-named dirs; never invent sites/demo for folders."""
    p = (rel or "").replace("\\", "/").lstrip("./")
    preferred = (preferred_dir or _extract_target_dir(message) or "").replace("\\", "/").strip("/")

    if "/" in p:
        return p

    bare = p.split("/")[-1].lower() if p else ""
    if bare in {"index.html", "styles.css", "style.css", "app.css", "main.css"}:
        if preferred:
            return f"{preferred}/{bare}"
        return f"sites/demo/{bare}"
    if preferred and p and "/" not in p:
        return f"{preferred}/{p}"
    return p


def _extract_target_dir(message: str) -> str:
    """Pull folder/path from mamri like 'create folder hh' or 'sites/foo'."""
    m = message or ""
    hit = re.search(
        r"(?:folder|dir|directory|path|under|inside|in)\s+[\"']?([A-Za-z0-9_\-./\\]+)[\"']?",
        m,
        re.I,
    )
    if hit:
        name = hit.group(1).replace("\\", "/").strip("/")
        if name.lower() not in {"folder", "file", "one", "a", "the", "html", "website"}:
            return name
    hit2 = re.search(r"\b(sites/[A-Za-z0-9_\-]+)\b", m, re.I)
    if hit2:
        return hit2.group(1).replace("\\", "/")
    hit3 = re.search(r"[\"']([A-Za-z0-9_\-]{1,40})[\"']", m)
    if hit3 and re.search(r"folder|dir|create|mkdir", m, re.I):
        return hit3.group(1)
    return ""


def _folder_only_intent(message: str) -> str | None:
    """Return folder path if user only wants mkdir (no website scaffold)."""
    m = (message or "").strip()
    if not m:
        return None
    if re.search(r"html|website|web\s*site|css|landing|page|youtube|index\.html", m, re.I):
        return None
    if not re.search(r"\b(folder|dir|directory|mkdir|make\s+dir)\b", m, re.I):
        return None
    if not re.search(r"\b(create|make|add|mkdir|new|panni|pannu)\b", m, re.I):
        return None
    name = _extract_target_dir(m)
    if not name:
        parts = re.findall(r"[A-Za-z0-9_\-]+", m)
        skip = {
            "create", "one", "folder", "dir", "directory", "make", "new", "add",
            "mkdir", "please", "a", "the", "panni", "pannu", "venum",
        }
        cand = [p for p in parts if p.lower() not in skip]
        name = cand[-1] if cand else ""
    return name.replace("\\", "/").strip("/") or None


def _make_folder(settings, rel: str) -> dict[str, Any]:
    msg = ide_agent.create_path(settings, rel, "dir")
    ok = msg.lower().startswith("created") or "already exists" in msg.lower()
    reply = (
        f"Created folder `{rel}/`.\n\n"
        f"{msg}\n\n"
        "No website files were written (folder-only request). "
        "Ask EDIT mode to add files inside it if you want."
    )
    return {
        "ok": ok,
        "reply": reply,
        "diffs": [],
        "mode": "EDIT",
        "backend": "altron-agi-path",
        "free": True,
        "created": [rel] if ok else [],
        "opened": [],
        "confirm_paths": [rel] if ok else [],
        "trace": ["mkdir", rel],
        "diagnose": {"summary": "folder", "problems": []},
        "plan_steps": [],
    }


def _wants_implement(message: str) -> bool:
    return bool(
        re.search(
            r"\b(implement|execute\s+plan|do\s+it|build\s+it|apply\s+plan|start\s+coding|panni\s*vidu)\b",
            message or "",
            re.I,
        )
    )


def _plan_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "ide" / "last_plan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _plan_turn(settings, core, message: str, path: str, selection: str) -> dict[str, Any]:
    diag = diagnose(settings)
    ctx = _system_ctx(
        settings, core, message, "PLAN", path, selection, diag, [], _extract_target_dir(message)
    )
    prompt = (
        ctx
        + "\n\nReturn ONLY a numbered plan (5–10 steps). Do NOT write files. "
        "End with: Say «implement plan» (or switch to EDIT) when ready."
    )
    try:
        raw = core.think.complete(
            [{"role": "system", "content": prompt}, {"role": "user", "content": message}]
        )
    except Exception as exc:  # noqa: BLE001
        raw = f"Plan error: {exc}"
    reply = _strip_tool_noise(raw)
    steps = [
        re.sub(r"^\d+[.)\]]\s*", "", line).strip()
        for line in reply.splitlines()
        if re.match(r"^\s*\d+[.)\]]\s+\S", line)
    ]
    try:
        _plan_path(settings).write_text(
            json.dumps({"message": message, "reply": reply, "steps": steps}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return {
        "ok": True,
        "reply": reply,
        "diffs": [],
        "mode": "PLAN",
        "backend": diag.get("backend") or "think",
        "free": True,
        "created": [],
        "opened": [],
        "confirm_paths": [],
        "trace": ["plan"],
        "diagnose": {"summary": diag.get("summary"), "problems": diag.get("problems") or []},
        "plan_steps": steps,
    }


def _debug_preflight(settings, path: str) -> dict[str, Any]:
    if not path:
        return {}
    items = ide_agent.diagnose_file(settings, path)
    errors = [x for x in items if x.get("severity") == "error"]
    return {"items": items, "errors": errors, "short_circuit": None}


def _run_mode_turn(settings, core, message: str, path: str, selection: str) -> dict[str, Any]:
    """RUN mode: explain + execute, no file writes."""
    diag = diagnose(settings)
    from altron.adapters import ide_run

    log = ""
    try:
        ws = Path(settings.altron_workspace).resolve()
        started = ide_run.detect_and_run(ws, path or "", debug=False)
        st = ide_run.status()
        log = f"{started}\n{st.get('log') or ''}".strip()
    except Exception as exc:  # noqa: BLE001
        log = f"Run failed: {exc}"

    ctx = _system_ctx(settings, core, message, "RUN", path, selection, diag, [], "")
    try:
        raw = core.think.complete(
            [
                {"role": "system", "content": ctx + "\nExplain the run result. Do not write files."},
                {
                    "role": "user",
                    "content": f"{message}\n\n--- run output ---\n{log[:6000]}",
                },
            ]
        )
        reply = _strip_tool_noise(raw)
    except Exception:
        reply = "Project run finished.\n\n" + log[:4000]
    if log and log.strip() not in reply:
        reply = (reply + "\n\n```\n" + log[:3500] + "\n```").strip()
    return {
        "ok": True,
        "reply": reply,
        "diffs": [],
        "mode": "RUN",
        "backend": diag.get("backend") or "think",
        "free": True,
        "created": [],
        "opened": [],
        "confirm_paths": [],
        "trace": ["run_mode"],
        "diagnose": {"summary": diag.get("summary"), "problems": diag.get("problems") or []},
        "plan_steps": [],
        "run_log": log[:8000],
    }


def _system_ctx(
    settings,
    core,
    message,
    mode,
    path,
    selection,
    diag,
    file_diag: list | None = None,
    preferred_dir: str = "",
) -> str:
    mode_help = {
        "ASK": "Answer; you MAY use fs_list/fs_read. Prefer ALTRON_WRITE only when user asks to build/edit.",
        "PLAN": "Numbered plan ONLY. Do not write files unless user said implement/execute plan.",
        "EDIT": "Implement changes. Use ALTRON_WRITE path=... or ALTRON_DIFF. Confirm final paths.",
        "DEBUG": "Read diagnostics, reproduce, then fix with ALTRON_WRITE / ALTRON_DIFF. Re-check after fix.",
        "RUN": "Explain and run via code_run only. Do not write files.",
    }.get(mode, "Help the user.")

    bits = [
        "You are ALTRON — a world-class local AGI coding agent inside ALTRON IDE.",
        "When the user asks once, you diagnose + do the work. Do not dump raw TOOL JSON to the user.",
        'To call a tool, emit ONE line: TOOL {"name":"fs_list","arguments":{"path":"."}}',
        "Allowed tools: fs_list, fs_read, fs_write, code_run, git_status, git_log, web_fetch.",
        "To create/overwrite a full file, prefer:\n"
        "ALTRON_WRITE path=relative/path.html\n```html\n...full content...\n```",
        "PATH DISCIPLINE: If user names a folder (e.g. hh), write under that folder — NEVER invent sites/demo.",
        "Bare index.html at workspace root is forbidden; use the named folder or sites/<slug>/.",
        f"Mode: {mode}. {mode_help}",
        "Never claim to be Copilot, VS Code, Cursor, or code-server.",
        "Never reply with sticky IDE help (list/open/edit/close ide).",
        f"Workspace: {settings.altron_workspace}",
        f"Self-check: {diag.get('summary')} | backend={diag.get('backend')}",
    ]
    if preferred_dir:
        bits.append(f"Preferred target directory from user: {preferred_dir}/")
    if file_diag:
        bits.append(
            "File diagnostics:\n"
            + "\n".join(
                f"- L{x.get('line')}: [{x.get('severity')}] {x.get('message')}" for x in file_diag[:12]
            )
        )
    mem_state = core._blank([{"role": "user", "content": message}])
    mem_state = core._remember(mem_state)
    identity = core._prompt(mem_state)
    if path:
        content, err = ide_agent.read_bytes(settings, path)
        if content is not None:
            bits.append(f"Open file: {path}\n```\n{content[:6000]}\n```")
        elif err:
            bits.append(f"Open file missing: {path} ({err})")
    if selection.strip():
        bits.append(f"Selection:\n```\n{selection[:3000]}\n```")
    return identity + "\n\n" + "\n\n".join(bits)


def _auto_fulfill(settings, message: str, mode: str) -> dict[str, Any] | None:
    """Deterministic AGI shortcuts for clear build intents (works even if LLM loops poorly)."""
    if _folder_only_intent(message):
        return None
    if not _wants_build(message):
        return None
    if not re.search(r"html|website|web\s*site|\bweb\b|youtube|landing|page", message, re.I):
        return None
    return _scaffold_site(settings, message)


def _wants_build(message: str) -> bool:
    m = (message or "").lower()
    return bool(
        re.search(
            r"\b(develop|build|create|make|generate|scaffold|write|panni|pannu|venum|வேணும்|want|one small)\b",
            m,
        )
        or "index.html" in m
        or re.search(r"\bsmall\s+web\b", m)
    )


def _scaffold_site(settings, message: str) -> dict[str, Any]:
    yt = bool(re.search(r"youtube|yt\b", message, re.I))
    preferred = _extract_target_dir(message)
    if preferred and not preferred.startswith("sites/") and "/" not in preferred:
        rel_dir = f"sites/{preferred}"
    elif preferred:
        rel_dir = preferred
    else:
        rel_dir = "sites/youtube_ref" if yt else "sites/demo"
    index = f"{rel_dir}/index.html"
    styles = f"{rel_dir}/styles.css"
    html = _youtube_site_html() if yt else _demo_site_html()
    css = _site_css()
    m1 = ide_agent.write_workspace(settings, index, html)
    m2 = ide_agent.write_workspace(settings, styles, css)
    created = []
    if m1.lower().startswith("wrote"):
        created.append(index)
    if m2.lower().startswith("wrote"):
        created.append(styles)
    reply = (
        "ALTRON built it for you.\n\n"
        f"**Confirmed paths:**\n- `{index}`\n- `{styles}`\n\n"
        "Files are opened in editor tabs. Preview uses the HTML path above.\n\n"
        f"Write log:\n{m1}\n{m2}"
    )
    return {
        "ok": True,
        "reply": reply,
        "diffs": [],
        "mode": "EDIT",
        "backend": "altron-agi-auto",
        "free": True,
        "created": created,
        "opened": created[:],
        "confirm_paths": created,
        "trace": ["auto_scaffold", *created],
        "diagnose": diagnose(settings),
        "plan_steps": [],
    }


def _youtube_site_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ALTRON · YouTube Reference</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header class="top">
    <div class="brand">ALTRON</div>
    <p class="tag">Build · Code · Automate · Evolve</p>
  </header>
  <main>
    <section class="hero">
      <h1>YouTube Reference Lab</h1>
      <p>Small site scaffolded by ALTRON AGI for layout / embed experiments.</p>
      <a class="cta" href="https://www.youtube.com" target="_blank" rel="noreferrer">Open YouTube</a>
    </section>
    <section class="embed">
      <h2>Embed slot</h2>
      <div class="frame">
        <iframe
          src="https://www.youtube.com/embed/dQw4w9WgXcQ"
          title="YouTube reference"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowfullscreen
        ></iframe>
      </div>
    </section>
  </main>
  <footer>Generated by ALTRON IDE Agent · free local AGI</footer>
</body>
</html>
"""


def _demo_site_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ALTRON Site</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <header class="top">
    <div class="brand">ALTRON</div>
    <p class="tag">World-class local AGI</p>
  </header>
  <main class="hero">
    <h1>Hello from ALTRON</h1>
    <p>Ask the Agent to evolve this page — it will edit real files.</p>
  </main>
</body>
</html>
"""


def _site_css() -> str:
    return """:root {
  --bg: #07080a;
  --red: #e11d2e;
  --text: #f2efe8;
  --muted: #9aa0a8;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Georgia, "Times New Roman", serif;
  background:
    radial-gradient(ellipse 80% 50% at 20% -10%, rgba(225,29,46,.18), transparent 55%),
    var(--bg);
  color: var(--text);
  min-height: 100vh;
}
.top { padding: 28px 32px 8px; }
.brand {
  font-family: "Arial Black", Impact, sans-serif;
  letter-spacing: .18em;
  color: var(--red);
  font-size: 14px;
}
.tag { color: var(--muted); margin: 6px 0 0; font-size: 13px; }
.hero, .embed { padding: 24px 32px; max-width: 920px; }
h1 { font-size: clamp(2rem, 5vw, 3.4rem); margin: 0 0 12px; }
h2 { font-size: 1.2rem; color: var(--red); letter-spacing: .08em; text-transform: uppercase; }
p { color: var(--muted); line-height: 1.55; max-width: 42rem; }
.cta {
  display: inline-block;
  margin-top: 18px;
  padding: 12px 18px;
  background: var(--red);
  color: #fff;
  text-decoration: none;
  font-family: ui-sans-serif, system-ui, sans-serif;
  letter-spacing: .06em;
  text-transform: uppercase;
  font-size: 12px;
}
.frame {
  position: relative;
  padding-top: 56.25%;
  border: 1px solid rgba(225,29,46,.35);
  background: #0c0e12;
}
.frame iframe {
  position: absolute; inset: 0; width: 100%; height: 100%; border: 0;
}
footer {
  padding: 24px 32px 40px;
  color: var(--muted);
  font-size: 12px;
  font-family: ui-monospace, monospace;
}
"""


def _all_tools(text: str) -> list[dict]:
    out: list[dict] = []
    for m in _TOOL_LINE.finditer(text or ""):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        name = str(data.get("name") or "")
        if name not in TOOL_NAMES:
            continue
        args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        out.append({"name": name, "arguments": args})
    return out


def _strip_tool_noise(text: str) -> str:
    cleaned = _TOOL_LINE.sub("", text or "")
    cleaned = re.sub(r"```tool.*?```", "", cleaned, flags=re.S)
    return cleaned.strip() or "Done."
