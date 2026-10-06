from altron.adapters import autonomous_goal as ag
from altron.adapters import flows_agent, flows_engine, flows_planner, flows_verify
from altron.settings import Settings


def _settings(tmp_path):
    return Settings(nvidia_nim_api_key="", altron_data_dir=tmp_path / "data", altron_workspace=tmp_path / "workspace")


def _save_safe_flow(settings, name="Test Safe Flow", extra_node=None):
    nodes = [
        {"id": "n1", "type": "trigger.manual", "label": "Start", "config": {}, "position": {"x": 80, "y": 180}},
    ]
    edges = []
    if extra_node is not None:
        nodes.append(extra_node)
        edges.append({"id": "e1", "source": "n1", "target": extra_node["id"], "sourceHandle": "default", "targetHandle": "in"})
    else:
        nodes.append(
            {
                "id": "n2",
                "type": "logic.log",
                "label": "Log",
                "config": {"message": "Automated test log"},
                "position": {"x": 320, "y": 180},
            }
        )
        edges.append({"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"})
    return flows_engine.save_flow(settings, {"name": name, "nodes": nodes, "edges": edges})


def _fixed_plan_workflow(_settings, _text):
    return flows_planner.enrich_plan(
        {
            "name": "Planner-Created Log Flow",
            "summary": "Logs a test message",
            "nodes": [
                {"id": "n1", "type": "trigger.manual", "label": "Start", "config": {}, "position": {"x": 80, "y": 180}},
                {
                    "id": "n2",
                    "type": "logic.log",
                    "label": "Log",
                    "config": {"message": "Created by planner"},
                    "position": {"x": 320, "y": 180},
                },
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default", "targetHandle": "in"}],
        }
    )


# TEST 1: existing-Flow goal selection
def test_flow_goal_selects_flow_capability_for_run_existing(tmp_path) -> None:
    settings = _settings(tmp_path)
    saved = _save_safe_flow(settings)
    capability, plan, meta = ag._plan_goal(f"Run flow {saved['name']}")
    assert capability == "flow"
    assert meta["flow_kind"] == "run_flow"


# TEST 2: existing Flow execution — real run occurs
def test_flow_goal_runs_existing_flow_successfully(tmp_path) -> None:
    settings = _settings(tmp_path)
    saved = _save_safe_flow(settings)
    state = ag.run_goal(settings, f"Run flow {saved['name']}")
    assert state["capability"] == "flow"
    assert state["status"] == "COMPLETED"
    assert state["flow_id"] == saved["id"]
    assert state["flow_run_id"]
    assert state["verification"]["ok"] is True


# TEST 3: Flow verification failure -> goal NOT marked completed
def test_flow_goal_reports_verification_failure(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    saved = _save_safe_flow(settings)
    monkeypatch.setattr(
        flows_verify, "verify_run", lambda s, f, r: {"ok": False, "checks": [{"name": "forced", "ok": False}]}
    )
    state = ag.run_goal(settings, f"Run flow {saved['name']}")
    assert state["status"] == "FAILED"
    assert state["verification"]["ok"] is False


# TEST 4: Flow execution failure -> existing Flow recovery (flows_recover) is consulted
def test_flow_goal_execution_failure_uses_existing_recovery(tmp_path) -> None:
    settings = _settings(tmp_path)
    broken_node = {
        "id": "n2",
        "type": "logic.delay",
        "label": "Bad Delay",
        "config": {"seconds": "notanumber"},
        "position": {"x": 320, "y": 180},
    }
    saved = _save_safe_flow(settings, name="Broken Flow", extra_node=broken_node)
    state = ag.run_goal(settings, f"Run flow {saved['name']}")
    assert state["status"] == "FAILED"
    run_obs = next(o for o in state["observations"] if o["step"] == "run_flow")
    assert run_obs["recovery"]  # existing flows_recover classification was consulted


# TEST 5: no uncontrolled nested retry loop — run_autonomous called exactly once
def test_flow_goal_does_not_double_retry(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    saved = _save_safe_flow(settings)
    calls = {"n": 0}
    real = flows_agent.run_autonomous

    def counting(settings_, flow_id, **kwargs):
        calls["n"] += 1
        return real(settings_, flow_id, **kwargs)

    monkeypatch.setattr(flows_agent, "run_autonomous", counting)
    ag.run_goal(settings, f"Run flow {saved['name']}")
    assert calls["n"] == 1


# TEST 6: Flow creation through existing flows_agi/planner -> validate -> save -> run
def test_flow_goal_creates_and_runs_new_flow(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(flows_planner, "plan_workflow", _fixed_plan_workflow)
    state = ag.run_goal(settings, "create a workflow that logs a test message and run it")
    assert state["capability"] == "flow"
    assert state["status"] == "COMPLETED"
    assert state["flow_id"]
    assert flows_engine.get_flow(settings, state["flow_id"]) is not None


# TEST 7: safety approval required for a risky Flow -> WAITING_FOR_APPROVAL, not auto-confirmed
def test_flow_goal_requires_approval_for_risky_flow(tmp_path) -> None:
    settings = _settings(tmp_path)
    risky_node = {
        "id": "n2",
        "type": "files.write",
        "label": "Write",
        "config": {"path": "somefile.txt", "content": "x"},
        "position": {"x": 320, "y": 180},
    }
    saved = _save_safe_flow(settings, name="Risky Flow", extra_node=risky_node)
    state = ag.run_goal(settings, f"Run flow {saved['name']}")
    assert state["status"] == "WAITING_FOR_APPROVAL"
    assert "CONFIRM" in state["result"]


# TEST 8: Mission Control (latest_state) reflects the Flow autonomous goal
def test_latest_state_reflects_flow_goal(tmp_path) -> None:
    settings = _settings(tmp_path)
    saved = _save_safe_flow(settings)
    ag.run_goal(settings, f"Run flow {saved['name']}")
    latest = ag.latest_state(settings)
    assert latest is not None
    assert latest["capability"] == "flow"
    assert latest["flow_id"] == saved["id"]
    assert latest["flow_run_id"]


# TEST 9: unsupported Flow request is not falsely reported as successful
def test_flow_goal_unsupported_shape_is_not_fake_success(tmp_path) -> None:
    settings = _settings(tmp_path)
    state = ag.run_goal(settings, "trigger the flow update process")
    assert state["status"] == "FAILED"
    assert "unsupported" in state["result"].lower()
