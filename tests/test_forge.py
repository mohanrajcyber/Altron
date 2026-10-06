import threading
from pathlib import Path

from altron.adapters import forge, ide_agi, ide_agent
from altron.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(
        nvidia_nim_api_key="",
        altron_data_dir=tmp_path / "data",
        altron_workspace=workspace,
    )


def test_build_intent_routes_only_project_creation() -> None:
    assert forge.is_build_request("ALTRON, create a Python port scanner with a clean UI")
    assert forge.is_build_request("Build me a dashboard")
    assert forge.is_build_request("Build a Python project and run it")
    assert not forge.is_build_request("Create a workflow that reads PDFs")
    assert not forge.is_build_request("Explain the scanner project")
    assert not forge.is_build_request("Open my project")
    assert forge.classify_request("Create a workflow for this") == "FLOW"
    assert forge.classify_request("Explain Python decorators") == "CHAT"
    assert forge.classify_request("Create a Python port scanner") == "BUILD_PROJECT"
    assert forge.classify_request("Build a Python calculator with a clean UI.") == "BUILD_PROJECT"
    assert forge.classify_request("Create a FastAPI REST API.") == "BUILD_PROJECT"


def test_forge_build_uses_ide_agent_and_confirms_files(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    observed = {}

    def fake_run_turn(*, settings, core, message, mode, project_root, on_progress):
        observed["message"] = message
        observed["mode"] = mode
        observed["project_root"] = project_root
        paths = [
            "forge_projects/port-scanner/scanner.py",
            "forge_projects/port-scanner/app.py",
        ]
        for path, content in zip(
            paths,
            ("def scan():\n    return []\n", "from scanner import scan\n\nprint(scan())\n"),
        ):
            assert ide_agent.write_workspace(settings, path, content).startswith("Wrote ")
            on_progress({"type": "file_written", "path": path})
        return {"created": paths, "reply": "Created the scanner project.", "trace": ["write"]}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)
    result = forge.run_build(settings, object(), "Create a Python port scanner with a clean UI")

    assert observed["mode"] == "EDIT"
    assert observed["project_root"] == "forge_projects/port-scanner"
    assert "forge_projects/port-scanner" in observed["message"]
    assert "127.0.0.1/localhost" in observed["message"]
    assert result["status"] == "COMPLETED"
    assert result["files"] == [
        "forge_projects/port-scanner/app.py",
        "forge_projects/port-scanner/scanner.py",
    ]
    assert result["validations"][0]["status"] == "PASSED"
    assert result["validations"][1]["status"] == "PASSED"
    assert result["validations"][2]["status"] == "NOT RUN"
    assert result["validations"][3]["status"] == "NOT RUN"


def test_forge_does_not_claim_missing_files_or_invalid_python(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    seen = {}

    def fake_run_turn(*, settings, core, message, mode, project_root, on_progress):
        bad_path = f"{project_root}/app.py"
        assert ide_agent.write_workspace(settings, bad_path, "if True print('broken')\n").startswith("Wrote ")
        seen["bad_path"] = bad_path
        return {"created": [bad_path, f"{project_root}/missing.py"]}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)

    result = forge.run_build(settings, object(), "Create a Python demo application")

    assert result["status"] == "FAILED"
    assert result["files"] == [seen["bad_path"]]
    assert result["validations"][0]["detail"] == "1 file(s) confirmed on disk"
    assert result["validations"][1]["status"] == "FAILED"
    assert any("missing.py" in error for error in result["errors"])


def test_forge_confirms_disk_files_when_agent_metadata_is_empty(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def fake_run_turn(*, settings, core, message, mode, project_root, on_progress):
        path = f"{project_root}/main.py"
        assert ide_agent.write_workspace(settings, path, "print('real file')\n").startswith("Wrote ")
        on_progress({"type": "file_written", "path": path})
        return {"created": [], "reply": "I created main.py."}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)
    result = forge.run_build(settings, object(), "Create a Python actual-file demo project")

    assert result["status"] == "COMPLETED"
    assert len(result["files"]) == 1
    assert result["files"][0].endswith("/main.py")


def test_forge_rejects_agent_prose_without_disk_files(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        forge.ide_agi,
        "run_turn",
        lambda **kwargs: {"created": [], "reply": "Created scanner.py and README.md successfully."},
    )

    result = forge.run_build(settings, object(), "Create a Python claim-only demo project")

    assert result["status"] == "FAILED"
    assert result["files"] == []
    assert result["validations"][0]["status"] == "FAILED"


def test_forge_uses_new_numbered_folder_instead_of_overwriting(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    existing = settings.altron_workspace / "forge_projects" / "port-scanner"
    existing.mkdir(parents=True)
    sentinel = existing / "keep.txt"
    sentinel.write_text("user data", encoding="utf-8")

    def fake_run_turn(*, settings, core, message, mode, project_root, on_progress):
        path = f"{project_root}/port_scanner.py"
        assert ide_agent.write_workspace(settings, path, "print('local only')\n").startswith("Wrote ")
        return {"created": [path]}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)

    result = forge.run_build(settings, object(), "Create a Python port scanner")

    assert result["status"] == "COMPLETED"
    assert result["project_dir"] == "forge_projects/port-scanner-2"
    assert sentinel.read_text(encoding="utf-8") == "user data"


def test_plan_only_invokes_existing_agent_without_creating_project(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    observed = {}

    def fake_run_turn(*, settings, core, message, mode, force_plan):
        observed["mode"] = mode
        observed["force_plan"] = force_plan
        return {"reply": "Plan from the IDE agent."}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)
    result = forge.run_build(settings, object(), "Create a Python sample application", plan_only=True)

    assert observed["mode"] == "PLAN"
    assert observed["force_plan"] is True
    assert result["status"] == "PLANNED"
    assert not (settings.altron_workspace / result["project_dir"]).exists()


def test_ide_agent_project_root_boundary() -> None:
    assert ide_agi._path_within_root("forge_projects/demo/app.py", "forge_projects/demo")
    assert not ide_agi._path_within_root("forge_projects/other/app.py", "forge_projects/demo")
    assert not ide_agi._path_within_root("forge_projects/demo/../outside.py", "forge_projects/demo")
    assert ide_agi._project_write_path("app.py", "forge_projects/demo") == "forge_projects/demo/app.py"
    assert ide_agi._project_write_path("./src/app.py", "forge_projects/demo") == "forge_projects/demo/src/app.py"
    assert ide_agi._project_write_path("../outside.py", "forge_projects/demo") is None
    assert ide_agi._project_write_path("forge_projects/other/app.py", "forge_projects/demo") is None


def test_explain_uses_actual_project_sources(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    path = "forge_projects/demo/app.py"
    ide_agent.write_workspace(settings, path, "print('real project')\n")
    seen = {}

    def fake_run_turn(*, settings, core, message, mode):
        seen["message"] = message
        seen["mode"] = mode
        return {"reply": "The app prints the real project marker."}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)
    result = forge.explain_project(settings, object(), "forge_projects/demo", "Explain this project")

    assert result["ok"] is True
    assert result["files"] == [path]
    assert "print('real project')" in seen["message"]
    assert seen["mode"] == "ASK"


def test_async_build_job_reports_real_milestones(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def fake_run_turn(*, settings, core, message, mode, project_root, on_progress):
        path = f"{project_root}/main.py"
        assert ide_agent.write_workspace(settings, path, "print('ready')\n").startswith("Wrote ")
        on_progress({"type": "file_written", "path": path})
        return {"created": [path], "reply": "Project created."}

    monkeypatch.setattr(forge.ide_agi, "run_turn", fake_run_turn)
    started = forge.start_build_job(settings, object(), "Create a Python job demo project")
    assert started["ok"] is True

    for _ in range(200):
        job = forge.build_job(started["id"])
        if job["status"] != "RUNNING":
            break
        threading.Event().wait(0.01)

    assert job["status"] == "COMPLETED"
    event_names = [event["event"] for event in job["events"]]
    assert event_names == [
        "request_accepted",
        "workspace_created",
        "generation_started",
        "file_written",
        "validation_started",
        "validation_finished",
        "build_finished",
    ]
    assert job["result"]["files"] == ["forge_projects/job-demo-project/main.py"]