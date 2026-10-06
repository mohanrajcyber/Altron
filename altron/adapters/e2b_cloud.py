from __future__ import annotations

from pathlib import Path


def run_python(code: str, sandbox: Path, e2b_api_key: str = "", local_runner=None) -> str:
    """E2B cloud sandbox when key + package exist; else local timeout sandbox."""
    from altron.adapters import sandbox as local

    runner = local_runner or local.run_python
    key = (e2b_api_key or "").strip()
    if key:
        try:
            return _e2b_run(code, key)
        except Exception as exc:  # noqa: BLE001
            result = runner(code, sandbox)
            return f"[local sandbox — E2B error: {exc}]\n{result}"
    result = runner(code, sandbox)
    return f"[local sandbox]\n{result}"


def _e2b_run(code: str, api_key: str) -> str:
    try:
        from e2b_code_interpreter import Sandbox
    except ImportError as exc:
        raise RuntimeError("pip install e2b-code-interpreter") from exc
    with Sandbox.create(api_key=api_key) as box:
        execution = box.run_code(code)
        logs = ""
        if getattr(execution, "logs", None):
            logs = "\n".join(getattr(execution.logs, "stdout", []) or []) + "\n".join(
                getattr(execution.logs, "stderr", []) or []
            )
        err = getattr(execution, "error", None)
        if err:
            return f"[e2b]\n{err}"
        text = logs.strip() or str(getattr(execution, "text", "") or "")
        return f"[e2b]\n{text or '(no output)'}"
