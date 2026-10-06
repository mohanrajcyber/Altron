from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 8
MAX_OUTPUT = 8_000
FORBIDDEN = (
    "NVIDIA_NIM",
    "nvapi-",
    ".env",
    "shutdown",
    "subprocess",
    "os.system",
    "ctypes",
    "winreg",
)


def run_python(code: str, sandbox: Path, runner=subprocess.run) -> str:
    source = (code or "").strip()
    if not source:
        return "No Python to run."
    lowered = source.lower()
    for mark in FORBIDDEN:
        if mark.lower() in lowered:
            return f"Blocked: sandbox forbids {mark}."
    sandbox.mkdir(parents=True, exist_ok=True)
    script = sandbox / "_run.py"
    script.write_text(source, encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "PYTHONIOENCODING": "utf-8",
        "TEMP": str(sandbox),
        "TMP": str(sandbox),
    }
    try:
        proc = runner(
            [sys.executable, str(script)],
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Sandbox timeout after {TIMEOUT_SECONDS}s."
    except OSError as exc:
        return f"Sandbox failed: {exc}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n…"
    return f"exit {proc.returncode}\n{out or '(no output)'}"
