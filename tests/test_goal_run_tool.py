from altron.adapters.tools import pick_action, run_tool
from altron.adapters.identity_store import IdentityStore
from altron.adapters.memory import JsonlMemory
from altron.settings import Settings


def _settings(tmp_path):
    return Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path)


def test_pick_action_recognizes_supported_goal(tmp_path) -> None:
    settings = _settings(tmp_path)
    picked = pick_action(
        "create a python program that prints Hello ALTRON, run it and verify the output", settings
    )
    assert picked is not None
    name, args = picked
    assert name == "goal_run"
    assert "python" in args["goal"].lower()


def test_pick_action_does_not_falsely_route_unsupported_goal(tmp_path) -> None:
    settings = _settings(tmp_path)
    # No python/program mention -> must not be routed to goal_run.
    assert pick_action("run it and verify", settings) != ("goal_run", {"goal": "run it and verify"})
    picked = pick_action("build me a cybersecurity portfolio website and test whether it works", settings)
    assert picked is None or picked[0] != "goal_run"
    picked2 = pick_action("run python: print(1+1)", settings)
    assert picked2 is not None and picked2[0] != "goal_run"


def test_goal_run_dispatches_to_autonomous_goal(tmp_path) -> None:
    settings = _settings(tmp_path)
    memory = JsonlMemory(settings.memory_path)
    identity = IdentityStore(settings.identity_path)
    result = run_tool(
        "goal_run",
        "create a python program that prints Hello ALTRON, run it and verify the output",
        memory,
        identity=identity,
        settings=settings,
    )
    assert "Goal:" in result
    assert "Status: COMPLETED" in result
    assert "Verification: PASS" in result
    # Real checkpoint written by the reused engine, not a fake response.
    goals_dir = tmp_path / "goals"
    assert goals_dir.is_dir() and any(goals_dir.iterdir())


def test_goal_run_reports_real_failure_not_fake_success(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    memory = JsonlMemory(settings.memory_path)
    identity = IdentityStore(settings.identity_path)

    from altron.adapters import autonomous_goal as ag

    def always_broken(*args, **kwargs):
        return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "Blocked: sandbox forbids not implemented"}

    monkeypatch.setattr(ag, "_cap_run_program", always_broken)
    result = run_tool(
        "goal_run",
        "create a python program that prints Hello ALTRON, run it and verify the output",
        memory,
        identity=identity,
        settings=settings,
    )
    assert "Status: FAILED" in result
    assert "completed" not in result.lower().split("status:")[1].split("\n")[0]
