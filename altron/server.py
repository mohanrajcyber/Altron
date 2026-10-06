from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from altron import __version__
from altron.adapters import comfy, flows_agent, flows_engine, flows_runtime, forge, ide_agent, ide_agi, ide_history, ide_run, ide_terminal, jobs, mcp_git, mission_control, n8n_live, pc_roots, traces
from altron.adapters.ollama import probe as probe_ollama
from altron.adapters.tools import TOOL_NAMES
from altron.adapters.workspace import resolve_allowed
from altron.graph import AltronCore
from altron.identity import IDENTITY_NAME
from altron.settings import get_settings
from altron.voice import status as voice_status

WEB = Path(__file__).resolve().parent / "web"
app = FastAPI(title="ALTRON", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
_core: AltronCore | None = None


@app.on_event("startup")
def _flows_runtime_startup() -> None:
    """Start Phase-1 schedule / file-watcher / app-started trigger loop."""
    from altron.adapters import checkpoint_store

    checkpoint_store.reconcile_on_boot(get_settings())
    flows_runtime.start(get_settings)


def get_core() -> AltronCore:
    global _core
    if _core is None:
        _core = AltronCore(get_settings())
    return _core


class ChatMessageIn(BaseModel):
    role: str
    content: Any = ""


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessageIn] = Field(default_factory=list)
    stream: bool = False


class MemoryIn(BaseModel):
    text: str
    kind: str = "note"


class JobIn(BaseModel):
    title: str
    payload: str = ""


def _organ_status(settings) -> dict[str, dict]:
    """Each organ is optional/conditional — report ok + a plain-English reason so
    the UI never silently falls back without telling the user why."""
    ollama = probe_ollama(settings)
    qdrant_ok = False
    qdrant_why = "Not configured"
    if (settings.qdrant_url or "").strip():
        try:
            import httpx

            r = httpx.get(f"{settings.qdrant_url.rstrip('/')}/collections", timeout=0.5)
            qdrant_ok = r.status_code < 500
            qdrant_why = "Reachable" if qdrant_ok else f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            qdrant_why = f"Unreachable ({type(exc).__name__}) — using local in-memory vectors"
    e2b_ok = bool(settings.e2b_api_key.strip())
    comfy_ok = bool(comfy.probe(settings.comfyui_url))
    return {
        "ollama": {
            "ok": bool(ollama.get("ok")),
            "why": "Reachable" if ollama.get("ok") else "Not running — start ./scripts/start_ollama.ps1 (falls back to local stub)",
            "models": ollama.get("models") or [],
        },
        "qdrant": {"ok": qdrant_ok, "why": qdrant_why},
        "e2b": {
            "ok": e2b_ok,
            "why": "API key set" if e2b_ok else "E2B_API_KEY not set — code_run falls back to local exec",
        },
        "comfy": {
            "ok": comfy_ok,
            "why": "Reachable" if comfy_ok else "Not running — start ./scripts/start_comfy.ps1 (image gen disabled)",
        },
    }


@app.get("/health")
@app.get("/api/status")
def health() -> dict:
    settings = get_settings()
    core = get_core()
    n8n = n8n_live.probe(settings.n8n_webhook_url, settings.n8n_base_url)
    voice = voice_status(settings)
    organs = _organ_status(settings)
    return {
        "ok": True,
        "name": IDENTITY_NAME,
        "think": settings.has_think_backend,
        "ollama": organs["ollama"]["ok"],
        "ollama_models": organs["ollama"]["models"],
        "memory": core.vectors.backend(),
        "e2b": organs["e2b"]["ok"],
        "n8n": n8n,
        "comfy": organs["comfy"]["ok"],
        "organs": organs,
        "voice": voice.get("face") or "browser",
        "livekit": voice.get("configured") or False,
        "model": settings.altron_model,
        "fallback": settings.altron_fallback_model,
        "keys": len(settings.api_keys),
        "version": __version__,
        "tools": TOOL_NAMES,
        "ide": ide_agent.probe(settings),
        "identity": {
            "human": len(core.identity.snapshot()["human"]),
            "workspace": len(core.identity.snapshot()["workspace"]),
        },
    }


@app.get("/api/identity")
def get_identity() -> dict:
    return get_core().identity.snapshot()


@app.get("/api/memory")
def list_memory() -> dict:
    return {"items": get_core().memory.recent(28)}


@app.post("/api/memory")
def write_memory(body: MemoryIn) -> dict:
    core = get_core()
    record = core.memory.write(body.text, kind=body.kind)
    core.vectors.add(body.text, kind=body.kind)
    return {"ok": True, "item": record}


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"items": jobs.recent(get_core().settings.jobs_path)}


@app.post("/api/jobs")
def enqueue_job(body: JobIn) -> dict:
    settings = get_core().settings
    message = n8n_live.enqueue(
        settings.jobs_path,
        body.title,
        body.payload,
        webhook_url=settings.n8n_webhook_url,
    )
    return {"ok": True, "message": message}


@app.get("/api/traces")
def list_traces() -> dict:
    return {"items": traces.recent(get_core().settings.traces_path)}


@app.get("/api/ide/status")
def ide_status() -> dict:
    settings = get_settings()
    return {"ok": True, **ide_agent.probe(settings), "run": ide_run.status()}


class IdeFileIn(BaseModel):
    path: str
    content: str = ""


class IdeRunIn(BaseModel):
    code: str = ""
    path: str = ""
    debug: bool = False


class IdeAgentIn(BaseModel):
    message: str
    path: str = ""
    selection: str = ""


class ForgeBuildIn(BaseModel):
    command: str
    plan_only: bool = False


class ForgeIntentIn(BaseModel):
    command: str


class ForgeExplainIn(BaseModel):
    message: str = "Explain what you created."
    project_dir: str
    mode: str = "ASK"


class ForgeRunIn(BaseModel):
    project_dir: str
    path: str


class IdePathIn(BaseModel):
    path: str
    kind: str = "file"


class IdeRenameIn(BaseModel):
    src: str
    dst: str


class IdeMoveIn(BaseModel):
    src: str
    dst_dir: str = "."


class IdeBranchIn(BaseModel):
    branch: str


class IdePrefsIn(BaseModel):
    autosave: bool | None = None
    extra_roots: list[str] | None = None
    bottom_height: int | None = None
    side_width: int | None = None
    agent_width: int | None = None


class IdeHistoryIn(BaseModel):
    id: str = ""
    path: str = ""


class IdeApplyIn(BaseModel):
    path: str
    old: str
    new: str


class IdeGitIn(BaseModel):
    files: list[str] = Field(default_factory=list)
    message: str = ""
    file: str = ""
    staged: bool = False


@app.get("/api/ide/tree")
def ide_tree(path: str = ".", depth: int = 2) -> dict:
    settings = get_settings()
    # Multi-root top-level when asking for workspace root
    if (path or ".") in {".", ""}:
        roots = ide_agent.tree_multi(settings, depth=depth)
        return {
            "ok": True,
            "workspace": str(Path(settings.altron_workspace).resolve()),
            "path": path or ".",
            "roots": roots,
            "items": roots[0]["items"] if roots else [],
        }
    return {
        "ok": True,
        "workspace": str(Path(settings.altron_workspace).resolve()),
        "path": path or ".",
        "items": ide_agent.tree(settings, path or ".", depth=depth),
    }


@app.get("/api/ide/files")
def ide_files(path: str = ".") -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve(), Path(settings.sandbox_path).resolve()]
    from altron.adapters import mcp_fs

    text = mcp_fs.fs_list(path or ".", roots, Path(settings.altron_workspace))
    return {"ok": True, "path": path or ".", "listing": text}


@app.get("/api/ide/flat")
def ide_flat() -> dict:
    settings = get_settings()
    return {"ok": True, "files": ide_agent.flat_files(settings)}


@app.get("/api/ide/search")
def ide_search(q: str = "") -> dict:
    settings = get_settings()
    return {"ok": True, "query": q, "hits": ide_agent.search_files(settings, q)}


@app.get("/api/ide/file")
def ide_file(path: str) -> dict:
    settings = get_settings()
    content, err = ide_agent.read_bytes(settings, path)
    if content is None:
        return {"ok": False, "path": path, "error": err}
    return {"ok": True, "path": path, "content": content}


@app.post("/api/ide/file")
def ide_file_write(body: IdeFileIn) -> dict:
    settings = get_settings()
    msg = ide_agent.write_workspace(settings, body.path, body.content)
    ok = not msg.lower().startswith("blocked") and not msg.lower().startswith("write failed")
    return {"ok": ok, "message": msg}


@app.post("/api/ide/mkdir")
def ide_mkdir(body: IdePathIn) -> dict:
    settings = get_settings()
    msg = ide_agent.create_path(settings, body.path, "dir")
    return {"ok": msg.lower().startswith("created"), "message": msg}


@app.post("/api/ide/create")
def ide_create(body: IdePathIn) -> dict:
    settings = get_settings()
    msg = ide_agent.create_path(settings, body.path, body.kind if body.kind in {"file", "dir"} else "file")
    return {"ok": msg.lower().startswith("created"), "message": msg}


@app.post("/api/ide/rename")
def ide_rename(body: IdeRenameIn) -> dict:
    settings = get_settings()
    msg = ide_agent.rename_path(settings, body.src, body.dst)
    return {"ok": msg.lower().startswith("renamed"), "message": msg}


@app.post("/api/ide/move")
def ide_move(body: IdeMoveIn) -> dict:
    settings = get_settings()
    msg = ide_agent.move_path(settings, body.src, body.dst_dir)
    return {"ok": msg.lower().startswith("renamed"), "message": msg}


@app.post("/api/ide/delete")
def ide_delete(body: IdePathIn) -> dict:
    settings = get_settings()
    msg = ide_agent.delete_path(settings, body.path)
    return {"ok": msg.lower().startswith("deleted"), "message": msg}


@app.post("/api/ide/run")
def ide_run_ep(body: IdeRunIn) -> dict:
    settings = get_settings()
    if body.path.strip():
        out = ide_agent.run_file(settings.intent_path, settings, body.path.strip())
    else:
        out = ide_agent.run_python(settings.intent_path, settings, body.code)
    return {"ok": True, "output": out}


@app.post("/api/ide/project/run")
def ide_project_run(body: IdeRunIn) -> dict:
    settings = get_settings()
    msg = ide_run.detect_and_run(Path(settings.altron_workspace), body.path, debug=bool(body.debug))
    return {"ok": True, "message": msg, **ide_run.status()}


@app.post("/api/ide/project/stop")
def ide_project_stop() -> dict:
    msg = ide_run.stop()
    return {"ok": True, "message": msg, **ide_run.status()}


@app.get("/api/ide/project/status")
def ide_project_status() -> dict:
    return {"ok": True, **ide_run.status()}


@app.get("/api/ide/debug/breakpoints")
def ide_debug_breakpoints_get() -> dict:
    from altron.adapters import ide_debug

    settings = get_settings()
    return {"ok": True, "breakpoints": ide_debug.list_breakpoints(settings)}


@app.post("/api/ide/debug/breakpoints/toggle")
def ide_debug_breakpoints_toggle(body: dict) -> dict:
    from altron.adapters import ide_debug

    settings = get_settings()
    bp = ide_debug.toggle_breakpoint(settings, str(body.get("file") or ""), int(body.get("line") or 0))
    return {"ok": True, "breakpoints": bp}


@app.post("/api/ide/debug/start")
def ide_debug_start(body: dict) -> dict:
    from altron.adapters import ide_debug

    settings = get_settings()
    return ide_debug.start_debug(settings, Path(settings.altron_workspace), str(body.get("path") or ""))


@app.post("/api/ide/debug/command")
def ide_debug_command(body: dict) -> dict:
    from altron.adapters import ide_debug

    return ide_debug.command(str(body.get("id") or ""), str(body.get("action") or ""), str(body.get("expr") or ""))


@app.get("/api/ide/debug/output")
def ide_debug_output(id: str = "") -> dict:
    from altron.adapters import ide_debug

    return ide_debug.output(id)


@app.post("/api/ide/debug/stop")
def ide_debug_stop(body: dict) -> dict:
    from altron.adapters import ide_debug

    return ide_debug.stop(str(body.get("id") or ""))


@app.post("/api/ide/start")
def ide_start() -> dict:
    settings = get_settings()
    msg = ide_agent.open_ide(settings.intent_path, settings)
    return {"ok": True, "message": msg, **ide_agent.probe(settings)}


@app.post("/api/ide/stop")
def ide_stop() -> dict:
    settings = get_settings()
    msg = ide_agent.close_ide(settings.intent_path, settings)
    return {"ok": True, "message": msg, **ide_agent.probe(settings)}


@app.post("/api/ide/terminal/create")
def ide_term_create() -> dict:
    settings = get_settings()
    sess = ide_terminal.create(Path(settings.altron_workspace))
    return {"ok": True, "id": sess.id, "cwd": str(sess.cwd)}


@app.post("/api/ide/terminal/input")
def ide_term_input(body: dict) -> dict:
    sid = str(body.get("id") or "")
    data = str(body.get("data") or "")
    sess = ide_terminal.get(sid)
    if not sess:
        return {"ok": False, "error": "no terminal"}
    sess.write(data)
    return {"ok": True}


@app.get("/api/ide/terminal/output")
def ide_term_output(id: str = "") -> dict:
    sess = ide_terminal.get(id)
    if not sess:
        return {"ok": False, "error": "no terminal", "data": ""}
    return {"ok": True, "data": sess.read(), "alive": sess.alive}


@app.post("/api/ide/terminal/kill")
def ide_term_kill(body: dict) -> dict:
    return {"ok": True, "message": ide_terminal.kill(str(body.get("id") or ""))}


@app.websocket("/api/ide/terminal/ws")
async def ide_term_ws(ws: WebSocket) -> None:
    await ws.accept()
    settings = get_settings()
    sess = ide_terminal.create(Path(settings.altron_workspace))
    await ws.send_json({"type": "ready", "id": sess.id, "cwd": str(sess.cwd)})
    import asyncio

    async def pump() -> None:
        while True:
            data = sess.read()
            if data:
                await ws.send_json({"type": "out", "data": data})
            if not sess.alive:
                await ws.send_json({"type": "exit"})
                break
            await asyncio.sleep(0.05)

    task = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "in":
                sess.write(str(msg.get("data") or ""))
            elif msg.get("type") == "kill":
                break
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        ide_terminal.kill(sess.id)


@app.get("/api/ide/git/status")
def ide_git_status() -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    data = mcp_git.git_status_porcelain(".", roots, roots[0])
    return {"ok": True, **data}


@app.get("/api/ide/git/diff")
def ide_git_diff(file: str = "", staged: bool = False) -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    text = mcp_git.git_diff(".", roots, roots[0], file=file, staged=staged)
    return {"ok": True, "diff": text}


@app.post("/api/ide/git/stage")
def ide_git_stage(body: IdeGitIn) -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, "message": mcp_git.git_stage(".", roots, roots[0], body.files)}


@app.post("/api/ide/git/unstage")
def ide_git_unstage(body: IdeGitIn) -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, "message": mcp_git.git_unstage(".", roots, roots[0], body.files)}


@app.post("/api/ide/git/commit")
def ide_git_commit(body: IdeGitIn) -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, "message": mcp_git.git_commit(".", roots, roots[0], body.message)}


@app.post("/api/ide/git/pull")
def ide_git_pull() -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, "message": mcp_git.git_pull(".", roots, roots[0])}


@app.post("/api/ide/git/init")
def ide_git_init() -> dict:
    settings = get_settings()
    ws = Path(settings.altron_workspace).resolve()
    try:
        proc = __import__("subprocess").run(
            ["git", "init"],
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
        )
        msg = (proc.stdout or proc.stderr or "").strip() or "git init done"
        return {"ok": proc.returncode == 0, "message": msg}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)}


@app.get("/api/ide/think/status")
def ide_think_status() -> dict:
    settings = get_settings()
    from altron.adapters.ollama import probe as probe_ollama

    ollama = probe_ollama(settings)
    if settings.api_keys:
        return {"ok": True, "backend": "nvidia-free", "label": "NVIDIA NIM (free tier keys)", "free": True}
    if ollama.get("ok"):
        models = ollama.get("models") or []
        return {
            "ok": True,
            "backend": "ollama-free",
            "label": f"Ollama · {(models[0] if models else 'local')}",
            "free": True,
            "models": models[:8],
        }
    return {
        "ok": True,
        "backend": "local-free",
        "label": "Local fallback (start Ollama for full AI)",
        "free": True,
    }


@app.post("/api/ide/git/push")
def ide_git_push() -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, "message": mcp_git.git_push(".", roots, roots[0])}


@app.get("/api/ide/git/branches")
def ide_git_branches() -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, **mcp_git.git_branches(".", roots, roots[0])}


@app.post("/api/ide/git/checkout")
def ide_git_checkout(body: IdeBranchIn) -> dict:
    settings = get_settings()
    roots = [Path(settings.altron_workspace).resolve()]
    return {"ok": True, "message": mcp_git.git_checkout(".", roots, roots[0], body.branch)}


@app.get("/api/ide/history")
def ide_history_list() -> dict:
    settings = get_settings()
    return {"ok": True, "items": ide_history.list_history(settings)}


@app.post("/api/ide/history/revert")
def ide_history_revert(body: IdeHistoryIn) -> dict:
    settings = get_settings()
    msg = ide_history.revert(settings, entry_id=body.id, path=body.path)
    return {"ok": msg.lower().startswith("reverted"), "message": msg}


@app.get("/api/ide/diagnostics")
def ide_diagnostics(path: str = "") -> dict:
    settings = get_settings()
    if path.strip():
        return {"ok": True, "items": ide_agent.diagnose_file(settings, path)}
    # active workspace scan of open-ish py files under altron/
    items: list[dict] = []
    for rel in ide_agent.flat_files(settings, max_n=80):
        if rel.endswith(".py") and ("altron/" in rel.replace("\\", "/") or rel.count("/") < 2):
            items.extend(ide_agent.diagnose_file(settings, rel)[:5])
        if len(items) >= 40:
            break
    return {"ok": True, "items": items}


@app.get("/api/ide/symbol")
def ide_symbol(q: str = "", path: str = "") -> dict:
    settings = get_settings()
    return {"ok": True, "hits": ide_agent.find_symbol(settings, q, path)}


@app.get("/api/ide/hover")
def ide_hover(path: str = "", line: int = 1, column: int = 1) -> dict:
    settings = get_settings()
    return ide_agent.hover_at(settings, path, line, column)


def _prefs_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "ide" / "prefs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@app.get("/api/ide/prefs")
def ide_prefs_get() -> dict:
    settings = get_settings()
    path = _prefs_path(settings)
    defaults = {
        "autosave": True,
        "extra_roots": [],
        "bottom_height": 200,
        "side_width": 250,
        "agent_width": 320,
        "workspace": str(Path(settings.altron_workspace).resolve()),
    }
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except json.JSONDecodeError:
            pass
    return {"ok": True, "prefs": defaults}


@app.post("/api/ide/prefs")
def ide_prefs_set(body: IdePrefsIn) -> dict:
    settings = get_settings()
    path = _prefs_path(settings)
    cur = ide_prefs_get()["prefs"]
    patch = body.model_dump(exclude_none=True)
    cur.update(patch)
    path.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return {"ok": True, "prefs": cur}


@app.get("/api/ide/diagnose")
def ide_diagnose() -> dict:
    settings = get_settings()
    return {"ok": True, **ide_agi.diagnose(settings)}


@app.post("/api/ide/agent")
def ide_agent_chat(body: IdeAgentIn) -> dict:
    """ALTRON AGI Agent — diagnose + tools + write files. Never dump raw TOOL JSON."""
    settings = get_settings()
    core = get_core()
    return ide_agi.run_turn(
        settings=settings,
        core=core,
        message=body.message,
        mode=body.mode,
        path=body.path,
        selection=body.selection,
    )


@app.post("/api/ide/agent/stream")
def ide_agent_stream(body: IdeAgentIn):
    """SSE stream of agent reply (chunked) + final metadata."""
    settings = get_settings()
    core = get_core()

    def gen():
        try:
            result = ide_agi.run_turn(
                settings=settings,
                core=core,
                message=body.message,
                mode=body.mode,
                path=body.path,
                selection=body.selection,
            )
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'text': str(exc)})}\n\n"
            return
        reply = result.get("reply") or ""
        step = 12
        for i in range(0, max(len(reply), 1), step):
            chunk = reply[i : i + step]
            yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
            time.sleep(0.012)
        meta = {
            "type": "done",
            "ok": True,
            "reply": reply,
            "diffs": result.get("diffs") or [],
            "mode": result.get("mode"),
            "backend": result.get("backend"),
            "free": result.get("free", True),
            "created": result.get("created") or [],
            "opened": result.get("opened") or [],
            "confirm_paths": result.get("confirm_paths") or [],
            "plan_steps": result.get("plan_steps") or [],
            "run_log": result.get("run_log") or "",
            "trace": result.get("trace") or [],
            "diagnose": result.get("diagnose") or {},
        }
        yield f"data: {json.dumps(meta)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/ide/preview-page")
def ide_preview_page(path: str) -> HTMLResponse:
    settings = get_settings()
    content, err = ide_agent.read_bytes(settings, path)
    if content is None:
        return HTMLResponse(f"<pre>Preview failed: {err or path}</pre>", status_code=404)
    parent = str(Path(path.replace("\\", "/")).parent).replace("\\", "/")
    if parent in {".", ""}:
        base = "/api/ide/raw/"
    else:
        base = f"/api/ide/raw/{parent}/"
    if "<base" not in content.lower():
        if re_search_head := __import__("re").search(r"(?i)<head[^>]*>", content):
            idx = re_search_head.end()
            content = content[:idx] + f'\n<base href="{base}">\n' + content[idx:]
        else:
            content = f'<base href="{base}">\n' + content
    return HTMLResponse(content)


@app.get("/api/ide/raw/{file_path:path}")
def ide_raw(file_path: str):
    import mimetypes

    settings = get_settings()
    content, err = ide_agent.read_bytes(settings, file_path)
    if content is None:
        return JSONResponse({"ok": False, "error": err or "missing"}, status_code=404)
    media = mimetypes.guess_type(file_path)[0] or "text/plain; charset=utf-8"
    return Response(content=content, media_type=media)


@app.post("/api/ide/agent/apply")
def ide_agent_apply(body: IdeApplyIn) -> dict:
    settings = get_settings()
    msg = ide_agent.apply_edit(settings, body.path, body.old, body.new)
    ok = "Edited" in msg or msg.lower().startswith("wrote")
    return {"ok": ok, "message": msg}


@app.get("/v1/models")
def list_models() -> dict:
    settings = get_settings()
    return {
        "object": "list",
        "data": [
            {"id": settings.altron_model, "object": "model", "owned_by": "altron"},
            {"id": settings.altron_fallback_model, "object": "model", "owned_by": "altron"},
            {"id": "altron", "object": "model", "owned_by": "altron"},
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(body: ChatRequest):
    messages = [{"role": m.role, "content": _as_text(m.content)} for m in body.messages]
    if body.stream:
        return StreamingResponse(
            _sse(messages, body.model or "altron"),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    state = get_core().run(messages)
    return JSONResponse(_completion_body(state, body.model or "altron"))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/ide")
def ide_page() -> FileResponse:
    """Full-page ALTRON IDE — open in a new tab from chat (`open ide`)."""
    return FileResponse(WEB / "ide.html")


@app.get("/forge")
def forge_page() -> FileResponse:
    return FileResponse(WEB / "forge.html")


@app.post("/api/forge/build")
def forge_build(body: ForgeBuildIn) -> dict:
    """Run a real build through the existing IDE agent and verify written files."""
    settings = get_settings()
    return forge.run_build(settings, get_core(), body.command, plan_only=body.plan_only)


@app.post("/api/forge/intent")
def forge_intent(body: ForgeIntentIn) -> dict:
    intent = forge.classify_request(body.command)
    return {"ok": True, "intent": intent, "build": intent == "BUILD_PROJECT"}


@app.post("/api/forge/jobs")
def forge_start_job(body: ForgeBuildIn) -> dict:
    settings = get_settings()
    return forge.start_build_job(settings, get_core(), body.command)


@app.get("/api/forge/jobs/{run_id}")
def forge_get_job(run_id: str) -> dict:
    job = forge.build_job(run_id)
    return {"ok": job is not None, "job": job}


@app.post("/api/forge/run")
def forge_run_project(body: ForgeRunIn) -> dict:
    settings = get_settings()
    root = Path(settings.altron_workspace).resolve()
    project_dir = body.project_dir.replace("\\", "/").strip("/")
    path = body.path.replace("\\", "/").strip("/")
    if not project_dir.startswith("forge_projects/") or not path.startswith(project_dir + "/"):
        return {"ok": False, "message": "Run is limited to a file inside this Forge project."}
    allowed = resolve_allowed(path, [root], base=root)
    if allowed is None or not allowed.is_file() or allowed.suffix.lower() not in {".py", ".js", ".mjs", ".cjs"}:
        return {"ok": False, "message": "Choose an existing Python or JavaScript source file in this project."}
    message = ide_run.detect_and_run(root, path)
    run_state = ide_run.status()
    return {"ok": message.startswith("Started:"), "message": message, **run_state}


@app.post("/api/forge/explain")
def forge_explain(body: ForgeExplainIn) -> dict:
    settings = get_settings()
    return forge.explain_project(settings, get_core(), body.project_dir, body.message)


@app.get("/flows")
def flows_page() -> FileResponse:
    """Full-page ALTRON Flows — n8n-style Jarvis automation UI (separate from IDE)."""
    return FileResponse(WEB / "flows.html")


@app.get("/mission-control")
def mission_control_page() -> FileResponse:
    """ALTRON Mission Control — observes existing Chat/IDE/Flows runtime, controls nothing new."""
    return FileResponse(WEB / "mission.html")


@app.get("/api/mission-control")
def mission_control_snapshot() -> dict:
    from altron.adapters import autonomous_goal

    settings = get_settings()
    data = mission_control.snapshot(settings)
    organs = _organ_status(settings)
    n8n = n8n_live.probe(settings.n8n_webhook_url, settings.n8n_base_url)
    voice = voice_status(settings)
    data["system"] = {
        "think": settings.has_think_backend,
        "model": settings.altron_model,
        "fallback_model": settings.altron_fallback_model,
        "organs": organs,
        "n8n": n8n,
        "ide": ide_agent.probe(settings),
        "voice": voice.get("face") or "browser",
        "livekit": voice.get("configured") or False,
    }
    data["autonomous_goal"] = autonomous_goal.latest_state(settings)
    return data


class FlowSaveIn(BaseModel):
    id: str = ""
    name: str = "Untitled flow"
    version: int = 1
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    variables: dict = Field(default_factory=dict)
    permissions: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class FlowRootIn(BaseModel):
    path: str = ""


class FlowTestNodeIn(BaseModel):
    node: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class FlowStopIn(BaseModel):
    run_id: str = ""


class FlowAutonomousIn(BaseModel):
    max_attempts: int = 3
    verify: bool = True
    resume_checkpoint: str = ""


@app.get("/api/flows/status")
def flows_status() -> dict:
    settings = get_settings()
    return flows_engine.status(settings)


@app.get("/api/flows/catalog")
def flows_catalog_route() -> dict:
    return {"ok": True, "nodes": flows_engine.catalog(), "categories": flows_engine.catalog_categories()}


@app.get("/api/flows/interrupted-runs")
def flows_interrupted_runs() -> dict:
    """Runs orphaned by a server crash/restart mid-flow — visible via durable SQLite checkpoints."""
    from altron.adapters import checkpoint_store

    settings = get_settings()
    return {"ok": True, "runs": checkpoint_store.list_interrupted(settings)}


@app.get("/api/flows/compile-hints")
def flows_compile_hints() -> dict:
    """DSPy-style hints compiled from judged failures — same hints injected into system prompt."""
    from altron.adapters import dspy_compile

    settings = get_settings()
    return {"ok": True, "hints": dspy_compile.compile_program(settings.traces_path)}


@app.get("/api/flows")
def flows_list() -> dict:
    settings = get_settings()
    return {"ok": True, "flows": flows_engine.list_flows(settings)}


@app.get("/api/flows/roots")
def flows_roots_get() -> dict:
    settings = get_settings()
    return {"ok": True, "roots": pc_roots.list_roots(settings)}


@app.post("/api/flows/roots")
def flows_roots_add(body: FlowRootIn) -> dict:
    settings = get_settings()
    return pc_roots.add_root(settings, body.path)


@app.post("/api/flows/roots/remove")
def flows_roots_remove(body: FlowRootIn) -> dict:
    settings = get_settings()
    return pc_roots.remove_root(settings, body.path)


@app.get("/api/flows/runs")
def flows_runs() -> dict:
    settings = get_settings()
    return {"ok": True, "runs": flows_engine.recent_runs(settings)}


@app.get("/api/flows/runs/{run_id}")
def flows_run_get(run_id: str) -> dict:
    settings = get_settings()
    run = flows_engine.get_run(settings, run_id)
    if not run:
        return {"ok": False, "message": "Run not found"}
    return {"ok": True, "run": run}


@app.get("/api/flows/checkpoints/{checkpoint_id}")
def flows_checkpoint_get(checkpoint_id: str) -> dict:
    settings = get_settings()
    ckpt = flows_agent.load_checkpoint(settings, checkpoint_id)
    if not ckpt:
        return {"ok": False, "message": "Checkpoint not found"}
    return {"ok": True, "checkpoint": ckpt}


@app.get("/api/flows/{flow_id}")
def flows_get(flow_id: str) -> dict:
    settings = get_settings()
    flow = flows_engine.get_flow(settings, flow_id)
    if not flow:
        return {"ok": False, "message": "Flow not found"}
    return {"ok": True, "flow": flow}


@app.post("/api/flows")
def flows_save(body: FlowSaveIn) -> dict:
    settings = get_settings()
    flow = flows_engine.save_flow(settings, body.model_dump())
    return {"ok": True, "flow": flow}


@app.post("/api/flows/{flow_id}/run")
def flows_run(flow_id: str) -> dict:
    settings = get_settings()
    return flows_engine.run_flow(settings, flow_id)


@app.post("/api/flows/{flow_id}/run/autonomous")
def flows_run_autonomous(flow_id: str, body: FlowAutonomousIn | None = None) -> dict:
    """Phase 3 — execute → observe → verify → bounded recovery."""
    settings = get_settings()
    body = body or FlowAutonomousIn()
    return flows_agent.run_autonomous(
        settings,
        flow_id,
        max_attempts=max(1, min(int(body.max_attempts or 3), 5)),
        verify=bool(body.verify),
        resume_checkpoint=str(body.resume_checkpoint or ""),
    )


@app.get("/api/flows/{flow_id}/checkpoints")
def flows_checkpoints(flow_id: str) -> dict:
    settings = get_settings()
    return {"ok": True, "checkpoints": flows_agent.list_checkpoints(settings, flow_id)}


@app.get("/api/flows/{flow_id}/run/stream")
def flows_run_stream(flow_id: str):
    settings = get_settings()

    def gen():
        for ev in flows_engine.run_flow_events(settings, flow_id):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/flows/run/stop")
def flows_run_stop(body: FlowStopIn) -> dict:
    return flows_engine.stop_run(body.run_id)


@app.post("/api/flows/test-node")
def flows_test_node(body: FlowTestNodeIn) -> dict:
    settings = get_settings()
    return flows_engine.test_node(settings, body.node, body.context)


@app.post("/api/flows/open")
def flows_open() -> dict:
    settings = get_settings()
    msg = flows_engine.open_flows_ui(settings)
    return {"ok": True, "message": msg}


@app.delete("/api/flows/{flow_id}")
def flows_delete(flow_id: str) -> dict:
    settings = get_settings()
    msg = flows_engine.delete_flow(settings, flow_id)
    return {"ok": True, "message": msg}


@app.get("/api/flows/{flow_id}/versions")
def flows_versions(flow_id: str) -> dict:
    settings = get_settings()
    return {"ok": True, "versions": flows_engine.list_versions(settings, flow_id)}


@app.post("/api/flows/{flow_id}/versions/{version_id}/restore")
def flows_restore_version(flow_id: str, version_id: str) -> dict:
    settings = get_settings()
    flow = flows_engine.restore_version(settings, flow_id, version_id)
    if not flow:
        return {"ok": False, "message": "Version not found"}
    return {"ok": True, "flow": flow}


@app.post("/api/flows/{flow_id}/undo")
def flows_undo(flow_id: str) -> dict:
    settings = get_settings()
    flow = flows_engine.undo_flow(settings, flow_id)
    if not flow:
        return {"ok": False, "message": "Nothing to undo"}
    return {"ok": True, "flow": flow}


@app.post("/api/flows/{flow_id}/duplicate")
def flows_duplicate(flow_id: str) -> dict:
    settings = get_settings()
    flow = flows_engine.duplicate_flow(settings, flow_id)
    if not flow:
        return {"ok": False, "message": "Flow not found"}
    return {"ok": True, "flow": flow}


class FlowWebhookIn(BaseModel):
    payload: dict = Field(default_factory=dict)


@app.post("/api/flows/hooks/{slug:path}")
@app.post("/hooks/{slug:path}")
async def flows_webhook(slug: str, body: dict | None = None) -> dict:
    """Fire a flow that has trigger.webhook matching this slug."""
    settings = get_settings()
    payload = body if isinstance(body, dict) else {}
    return flows_runtime.handle_webhook(settings, slug, payload)

def _sse(messages: list[dict], model: str):
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    final: dict[str, Any] | None = None
    try:
        for event in get_core().stream_turn(messages):
            kind = event.get("type")
            if kind == "meta":
                yield _sse_line({"type": "altron.meta", **{k: v for k, v in event.items() if k != "type"}})
            elif kind == "token":
                chunk = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": event.get("text") or ""},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif kind == "done":
                final = event.get("state")
    except Exception as exc:  # noqa: BLE001 — keep UI alive if a tool/thread crashes
        err = f"ALTRON hit an internal error but is still running: {exc}"
        chunk = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": err}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    done = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
    if final:
        yield _sse_line(
            {
                "type": "altron.done",
                "trace": final.get("trace"),
                "judgment": final.get("judgment"),
            }
        )
    yield "data: [DONE]\n\n"


def _sse_line(payload: dict[str, Any]) -> str:
    return f"event: altron\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _completion_body(state: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": state.get("reply") or ""},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "altron": {"trace": state.get("trace"), "judgment": state.get("judgment")},
    }


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content or "")


if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB), name="assets")
