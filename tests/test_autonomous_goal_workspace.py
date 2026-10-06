from pathlib import Path

from altron.adapters import autonomous_goal as ag
from altron.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path / "data", altron_workspace=ws)


# TEST 1: workspace inspection (read-only, before any write)
def test_inspect_workspace_reports_new_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    result = ag._cap_inspect_workspace(settings, "calculator_project")
    assert result["ok"] is True
    assert result["blocked"] is False
    assert result["exists"] is False


# TEST 2 + 3: create a Python project + run it successfully
def test_workspace_goal_success_create_run_verify(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = ag.run_goal(
        settings,
        "create a python calculator project in my workspace that prints Calculator Ready, run it and verify",
    )
    assert state["capability"] == "ide_workspace"
    assert state["status"] == "COMPLETED"
    assert state["verification"]["ok"] is True
    # Real file on disk under the real workspace (not sandbox), via ide_agent.write_workspace.
    created = next(o for o in state["observations"] if o["step"] == "create_file")
    assert Path(created["path"]).is_file()
    assert Path(created["path"]).is_relative_to(settings.altron_workspace)


# TEST 4: verification failure despite a successful run
def test_workspace_goal_verification_fails_when_output_missing(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def wrong_output(settings_, rel_path):
        return {"ok": True, "exit_code": 0, "stdout": "unexpected", "stderr": ""}

    monkeypatch.setattr(ag, "_cap_run_workspace_file", wrong_output)
    state = ag.run_goal(settings, "create a python demo project in my workspace that prints Marker, run it and verify")
    assert state["status"] == "FAILED"
    assert state["verification"]["ok"] is False


# TEST 5: intentional syntax error -> recover -> success
def test_workspace_goal_recovers_from_syntax_error(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    calls = {"n": 0}
    real_generate = ag._generate_code

    def broken_then_fixed(print_text: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return f'print("{print_text}"\n'
        return real_generate(print_text)

    monkeypatch.setattr(ag, "_generate_code", broken_then_fixed)
    state = ag.run_goal(settings, "create a python tool project in my workspace that prints Fixed OK, run it and verify")
    assert state["capability"] == "ide_workspace"
    assert state["status"] == "COMPLETED"
    assert state["attempt"] >= 2


# TEST 6: permanent failure -> bounded retries
def test_workspace_goal_permanent_failure_bounded_retries(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def always_broken(settings_, rel_path):
        return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "Blocked: sandbox forbids not implemented"}

    monkeypatch.setattr(ag, "_cap_run_workspace_file", always_broken)
    state = ag.run_goal(
        settings,
        "create a python util project in my workspace that prints X, run it and verify",
        max_attempts=3,
    )
    assert state["status"] == "FAILED"
    assert state["attempt"] <= 3


# TEST 7: path outside trusted root -> blocked (existing resolve_allowed reused as-is)
def test_workspace_goal_blocks_path_outside_trusted_root(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = ag.run_goal(
        settings,
        "create a python project in my workspace that prints X, run it and verify",
        context={"project_dir": "../outside_workspace_root"},
    )
    assert state["status"] == "FAILED"
    assert "Blocked path" in state["result"]


# TEST 8: cancellation stops safely before any file is written
def test_workspace_goal_cancellation_stops_before_inspect(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    seen = {}

    def on_ready(run_id: str) -> None:
        seen["run_id"] = run_id
        ag.cancel_goal(run_id)

    state = ag.run_goal(
        settings,
        "create a python project in my workspace that prints Never Runs, run it and verify",
        on_ready=on_ready,
    )
    assert state["status"] == "CANCELLED"
    assert not any(tmp_path.glob("workspace/**/*.py"))


# TEST 9: Mission Control read path reflects the current/latest workspace goal
def test_latest_state_reflects_workspace_goal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ag.run_goal(settings, "create a python status project in my workspace that prints Live, run it and verify")
    latest = ag.latest_state(settings)
    assert latest is not None
    assert latest["capability"] == "ide_workspace"
    assert latest["status"] == "COMPLETED"
