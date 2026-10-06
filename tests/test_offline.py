from pathlib import Path

from altron.adapters import computer
from altron.adapters.judge import critique
from altron.adapters.memory import JsonlMemory
from altron.adapters.tools import pick_tool, run_tool
from altron.graph import AltronCore
from altron.identity import IDENTITY_NAME, system_prompt
from altron.settings import Settings


def test_identity() -> None:
    assert IDENTITY_NAME == "ALTRON"
    assert "organs" in system_prompt().lower() or "brain" in system_prompt().lower()


def test_memory_roundtrip(tmp_path: Path) -> None:
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    mem.write("user likes Tamil + English")
    hits = mem.search("tamil")
    assert hits
    assert "Tamil" in hits[0]


def test_remember_tool(tmp_path: Path) -> None:
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    assert pick_tool("remember that the core is ALTRON") == "memory_write"
    result = run_tool("memory_write", "remember that the core is ALTRON", mem)
    assert "ALTRON" in result
    assert mem.search("core")


def test_judge_blocks_nvidia_key_echo() -> None:
    assert critique("hi", "here is nvapi-AAAAAAAAAAAAAAAAAAAAAAAA") == "possible_secret_leak"
    assert critique("who are you", "I am ALTRON") == "ok"


def test_memory_recent(tmp_path: Path) -> None:
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    mem.write("alpha")
    mem.write("beta")
    assert mem.recent(1)[0]["text"] == "beta"


def test_stream_act_without_keys(tmp_path: Path) -> None:
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)
    core = AltronCore(settings)
    events = list(core.stream_turn([{"role": "user", "content": "remember that desk folder is AGI"}]))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "meta"
    assert "token" in kinds
    assert kinds[-1] == "done"
    assert "AGI" in (events[-1]["state"]["reply"] or "")


def test_identity_survives_new_core(tmp_path: Path) -> None:
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)
    first = AltronCore(settings)
    first.run([{"role": "user", "content": "remember that this workspace is ALTRON"}])
    second = AltronCore(settings)
    facts = second.identity.all_facts()
    assert any("ALTRON" in fact for fact in facts)
    prompt = second._prompt({"memories": facts, "messages": []})
    assert "Workspace memory" in prompt
    assert "ALTRON" in prompt


def test_graph_act_without_keys(tmp_path: Path) -> None:
    settings = Settings(
        nvidia_nim_api_key="",
        altron_data_dir=tmp_path,
    )
    core = AltronCore(settings)
    state = core.run([{"role": "user", "content": "remember that desk folder is AGI"}])
    assert state["plan"] == "act"
    assert "AGI" in (state["reply"] or "")
    assert "judge:ok" in " ".join(state["trace"] or [])


def test_pick_computer_tools() -> None:
    assert pick_tool("okk open new tab") == "browser_open"
    assert pick_tool("open browser") == "browser_open"
    assert pick_tool("open youtube") == "youtube_open"
    assert pick_tool("youtube open") == "youtube_open"
    assert pick_tool("youtube search tamil songs") == "youtube_search"
    assert pick_tool("close the youtube") == "youtube_close"
    assert pick_tool("can you plz switchoff my pc") == "shutdown_request"
    assert pick_tool("CONFIRM SHUTDOWN") == "shutdown_confirm"
    assert pick_tool("open notepad") == "open_notepad"
    assert pick_tool("open ida") == "open_ida"
    assert pick_tool("launch ida pro") == "open_ida"
    assert pick_tool("hey ALTRON spotify") == "spotify_open"
    assert pick_tool("ALTRON spotify") == "spotify_open"
    assert pick_tool("spotify tab") == "spotify_open"
    assert pick_tool("open spotify tab") == "spotify_open"


def test_open_ida_resolution(monkeypatch) -> None:
    monkeypatch.setattr(computer, "resolve_app", lambda name: {"ida.exe": r"C:\\Tools\\IDA\\ida.exe"}.get(name))
    result = computer.open_app("ida")
    assert "C:\\Tools\\IDA\\ida.exe" in result
    assert "IDA" in result


def test_shutdown_never_runs_without_confirm(monkeypatch) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(computer, "launch_process", lambda args: called.append(args))
    ask = computer.shutdown_request(confirmed=False)
    assert called == []
    assert "CONFIRM SHUTDOWN" in ask
    confirm = computer.shutdown_request(confirmed=True)
    assert called == [["shutdown", "/s", "/t", "30"]]
    assert "30 seconds" in confirm


def test_open_tab_act_without_opening(monkeypatch, tmp_path: Path) -> None:
    from altron.adapters import browser_control

    monkeypatch.setattr(
        browser_control,
        "open_browser",
        lambda intent_path, url="": "Browser under ALTRON control — opened https://www.google.com",
    )
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)
    core = AltronCore(settings)
    state = core.run([{"role": "user", "content": "open new tab"}])
    assert state["plan"] == "act"
    assert "ALTRON control" in (state["reply"] or "")


def test_casual_shutdown_is_gated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(computer, "launch_process", lambda args: (_ for _ in ()).throw(AssertionError("shutdown ran")))
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)
    core = AltronCore(settings)
    state = core.run([{"role": "user", "content": "can you plz switchoff my pc"}])
    assert state["plan"] == "act"
    assert "CONFIRM SHUTDOWN" in (state["reply"] or "")


def test_phase2_identity_file_roundtrip(tmp_path: Path) -> None:
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)
    first = AltronCore(settings)
    first.run([{"role": "user", "content": "remember that my name is the developer"}])
    assert (tmp_path / "identity.json").exists()
    assert (tmp_path / "memory.jsonl").exists()
    third = AltronCore(settings)
    assert any("developer" in fact.lower() for fact in third.identity.all_facts())


def test_mcp_fs_allowlist(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello altron", encoding="utf-8")
    (tmp_path / ".env").write_text("NVIDIA_NIM_API_KEY=secret", encoding="utf-8")
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path, altron_workspace=tmp_path)
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    listed = run_tool("fs_list", "list files", mem, args={"path": "."}, settings=settings)
    assert "README.md" in listed
    readme = run_tool("fs_read", "read file README.md", mem, args={"path": "README.md"}, settings=settings)
    assert "hello altron" in readme
    blocked = run_tool("fs_read", "read file .env", mem, args={"path": ".env"}, settings=settings)
    assert "Blocked" in blocked
    outside = run_tool("fs_read", "read", mem, args={"path": "../API.txt"}, settings=settings)
    assert "Blocked" in outside


def test_code_sandbox(tmp_path: Path) -> None:
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path, altron_workspace=tmp_path)
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    result = run_tool("code_run", "run python print(2+2)", mem, args={"code": "print(2+2)"}, settings=settings)
    assert "4" in result
    denied = run_tool("code_run", "bad", mem, args={"code": "import subprocess"}, settings=settings)
    assert "Blocked" in denied


def test_pick_phase3_tools() -> None:
    assert pick_tool("list files") == "fs_list"
    assert pick_tool("fetch https://example.com") == "web_fetch"
    assert pick_tool("run python print(1)") == "code_run"
    assert pick_tool("git status") == "git_status"


def test_web_fetch_blocks_localhost(monkeypatch, tmp_path: Path) -> None:
    from altron.adapters import mcp_fetch

    mem = JsonlMemory(tmp_path / "memory.jsonl")
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path, altron_workspace=tmp_path)
    blocked = run_tool("web_fetch", "fetch http://127.0.0.1/", mem, args={"url": "http://127.0.0.1/"}, settings=settings)
    assert "Blocked" in blocked
    monkeypatch.setattr(mcp_fetch, "is_public_http_url", lambda url: True)
    monkeypatch.setattr(mcp_fetch, "http_get", lambda url, timeout=12.0: (200, "text/plain", b"ok-page"))
    fetched = run_tool("web_fetch", "fetch https://example.com", mem, args={"url": "https://example.com"}, settings=settings)
    assert "ok-page" in fetched


def test_tool_directive_parser() -> None:
    from altron.adapters.tools import parse_tool_directive

    parsed = parse_tool_directive('TOOL {"name":"fs_list","arguments":{"path":"."}}')
    assert parsed is not None
    assert parsed["name"] == "fs_list"


def test_job_queue(tmp_path: Path) -> None:
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path, altron_workspace=tmp_path)
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    queued = run_tool("job_enqueue", "enqueue backup", mem, args={"title": "backup"}, settings=settings)
    assert "Queued" in queued
    listed = run_tool("job_list", "list jobs", mem, settings=settings)
    assert "backup" in listed


def test_vector_memory_search(tmp_path: Path) -> None:
    from altron.adapters.vector_memory import VectorMemory

    vm = VectorMemory(tmp_path / "vectors.jsonl")
    vm.add("ALTRON loves Tamil and English chats")
    vm.add("unrelated cooking recipe")
    hits = vm.search("tamil language")
    assert hits
    assert any("Tamil" in h or "ALTRON" in h for h in hits)


def test_graphiti_local(tmp_path: Path) -> None:
    from altron.adapters.graphiti_local import KnowledgeGraph

    g = KnowledgeGraph(tmp_path / "graph.json")
    assert "ALTRON" in g.add("ALTRON", "runs_on", "Windows")
    found = g.search("Windows")
    assert "runs_on" in found


def test_browser_falls_back_without_playwright(monkeypatch, tmp_path: Path) -> None:
    from altron.adapters import browser_agent, mcp_fetch

    monkeypatch.setattr(browser_agent, "is_public_http_url", lambda url: True)
    monkeypatch.setattr(browser_agent, "web_fetch", lambda url: f"fetched:{url}")
    monkeypatch.setattr(mcp_fetch, "web_fetch", lambda url: f"fetched:{url}")

    import builtins

    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError("no playwright")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    out = browser_agent.browse("https://example.com")
    assert "Playwright not installed" in out
    assert "fetched:https://example.com" in out


def test_browser_session_reopens_after_manual_close(monkeypatch) -> None:
    from altron.adapters import browser_session

    calls: list[str] = []

    def fake_submit(fn, args, kwargs, timeout):
        if not calls:
            calls.append("first")
            raise RuntimeError("Target page, context or browser has been closed")
        calls.append("retry")
        return "ok"

    monkeypatch.setattr(browser_session, "_ensure_worker", lambda: None)
    monkeypatch.setattr(browser_session, "_submit", fake_submit)
    monkeypatch.setattr(browser_session, "close_session", lambda: "closed")

    result = browser_session.run(lambda page: "ok", reset_on_closed=True)
    assert result == "ok"
    assert calls == ["first", "retry"]


def test_voice_command_normalizer_requires_wake_word() -> None:
    from altron.adapters.tools import normalize_voice_command

    assert normalize_voice_command("hey ALTRON open browser") == "open browser"
    assert normalize_voice_command("ALTRON close browser") == "close browser"
    assert normalize_voice_command("hello there") == ""
    assert normalize_voice_command("search for cats", sticky_mode=True) == "search for cats"


def test_run_app_uses_fast_browser_startup(monkeypatch, tmp_path: Path) -> None:
    import builtins

    from altron.desktop import run_app

    seen: dict[str, float | str] = {}

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        def run(self):
            return None

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "webview":
            raise ImportError("no webview")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr("uvicorn.Config", FakeConfig)
    monkeypatch.setattr("uvicorn.Server", FakeServer)

    def fake_wait(host: str, port: int, timeout: float = 3.0) -> bool:
        seen["timeout"] = timeout
        return True

    monkeypatch.setattr("altron.desktop._wait_port", fake_wait)
    monkeypatch.setattr("altron.desktop.webbrowser.open", lambda url: seen.setdefault("url", url))

    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)
    result = run_app(settings)

    assert result == 0
    assert float(seen.get("timeout", 0)) <= 3.0
    assert str(seen.get("url", "")).startswith("http://")


def test_code_run_local_prefix(tmp_path: Path) -> None:
    settings = Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path, altron_workspace=tmp_path, e2b_api_key="")
    mem = JsonlMemory(tmp_path / "memory.jsonl")
    result = run_tool("code_run", "run python print(3)", mem, args={"code": "print(3)"}, settings=settings)
    assert "local sandbox" in result
    assert "3" in result


def test_browser_allowlist_and_steps() -> None:
    from altron.adapters import browser_agent

    assert browser_agent.host_allowed("https://example.com")
    assert not browser_agent.host_allowed("https://evil.example.net")
    steps = browser_agent.parse_steps('click "More information" | wait 0.2 | read')
    assert steps[0]["action"] == "click_text"
    assert steps[1]["action"] == "wait"
    assert pick_tool('browse https://example.com | click "More information"') == "browser_use"



def test_local_think_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY_2", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY_3", raising=False)
    monkeypatch.setattr("altron.adapters.think.probe", lambda *a, **k: {"ok": False, "models": []})
    settings = Settings(_env_file=None, nvidia_nim_api_key="", altron_data_dir=tmp_path)
    core = AltronCore(settings)
    state = core.run([{"role": "user", "content": "who are you"}])
    assert not settings.api_keys
    assert state["backend"] == "local"
    assert "ALTRON" in (state["reply"] or "")
    assert (tmp_path / "traces.jsonl").exists()


def test_ollama_used_when_nvidia_missing(monkeypatch, tmp_path: Path) -> None:
    from altron.adapters.think import ThinkAdapter, ThinkDecision

    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY_2", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY_3", raising=False)
    monkeypatch.setattr("altron.adapters.think.probe", lambda *a, **k: {"ok": True, "models": ["llama3.1"]})
    monkeypatch.setattr(
        ThinkAdapter,
        "_ollama_decide",
        lambda self, messages, tools, available: ThinkDecision(text="hello from ollama", backend="ollama"),
    )
    settings = Settings(_env_file=None, nvidia_nim_api_key="", altron_data_dir=tmp_path)
    core = AltronCore(settings)
    state = core.run([{"role": "user", "content": "who are you"}])
    assert state["backend"] == "ollama"
    assert "ollama" in (state["reply"] or "").lower()


def test_trace_compile_hints(tmp_path: Path) -> None:
    from altron.adapters import traces
    from altron.identity import system_prompt

    path = tmp_path / "traces.jsonl"
    traces.write(path, {"user": "hi", "reply": "as an ai language model x", "judgment": "stock_disclaimer"})
    hint = traces.compile_hints(path)
    assert "stock_disclaimer" in hint
    prompt = system_prompt(hints=hint)
    assert "Compiled from traces" in prompt
