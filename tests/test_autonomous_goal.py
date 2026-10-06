from pathlib import Path

from altron.adapters import autonomous_goal as ag
from altron.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)


def test_goal_success_create_run_verify(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = ag.run_goal(settings, "create a python program that prints Hello ALTRON, run it and verify")
    assert state["status"] == "COMPLETED"
    assert state["verification"]["ok"] is True
    assert state["attempt"] == 1
    # Checkpoint persisted to disk (data/goals/<run_id>.json)
    ckpt = tmp_path / "goals" / f"{state['run_id']}.json"
    assert ckpt.is_file()


def test_goal_recovers_from_syntax_error(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    # Force the first _cap_create_file call to write broken code (missing paren),
    # then let the real deterministic repair fix it on retry.
    calls = {"n": 0}
    real_generate = ag._generate_code

    def broken_then_fixed(print_text: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return f'print("{print_text}"\n'  # missing closing paren -> SyntaxError
        return real_generate(print_text)

    monkeypatch.setattr(ag, "_generate_code", broken_then_fixed)
    state = ag.run_goal(settings, "create a python program that prints Recovered OK, run it and verify")
    assert state["status"] == "COMPLETED"
    assert state["attempt"] >= 2
    assert any(e for e in state["errors"] if isinstance(e, dict))


def test_goal_permanent_failure_bounded_retries(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def always_broken(*args, **kwargs):
        return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "Blocked: sandbox forbids not implemented"}

    monkeypatch.setattr(ag, "_cap_run_program", always_broken)
    state = ag.run_goal(settings, "create a python program that prints X, run it and verify", max_attempts=3)
    assert state["status"] == "FAILED"
    assert state["attempt"] <= 3


def test_goal_cancellation_stops_safely(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    seen = {}

    def on_ready(run_id: str) -> None:
        seen["run_id"] = run_id
        ag.cancel_goal(run_id)

    state = ag.run_goal(settings, "create a python program that prints Never Runs", on_ready=on_ready)
    assert state["status"] == "CANCELLED"
    assert seen["run_id"] == state["run_id"]


def test_goal_verification_fails_when_output_missing(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def wrong_output(script_path: str):
        return {"ok": True, "exit_code": 0, "stdout": "not the expected text", "stderr": ""}

    monkeypatch.setattr(ag, "_cap_run_program", wrong_output)
    state = ag.run_goal(settings, "create a python program that prints Specific Marker Text, run it and verify")
    assert state["status"] == "FAILED"
    assert state["verification"]["ok"] is False
    assert "verification failed" in state["result"].lower()
