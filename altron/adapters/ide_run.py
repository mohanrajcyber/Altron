from __future__ import annotations

"""ALTRON IDE process runners — Run/Stop (not code-server)."""

import os
import subprocess
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_log: list[str] = []
_meta: dict = {"running": False, "cmd": "", "started": 0.0, "exit_code": None}


def status() -> dict:
    with _lock:
        running = _proc is not None and _proc.poll() is None
        return {
            "running": running,
            "cmd": _meta.get("cmd") or "",
            "started": _meta.get("started") or 0,
            "exit_code": None if running else _meta.get("exit_code"),
            "log": "".join(_log[-200:]),
        }


def stop() -> str:
    global _proc
    with _lock:
        if _proc is None or _proc.poll() is not None:
            return "No running process."
        proc = _proc
    try:
        if os.name == "nt":
            proc.terminate()
            time.sleep(0.4)
            if proc.poll() is None:
                proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    except OSError as exc:
        return f"Stop failed: {exc}"
    with _lock:
        _meta["running"] = False
        _meta["exit_code"] = proc.poll()
    return "Stopped."


def start(cmd: list[str], cwd: Path) -> str:
    global _proc
    stop()
    cwd = Path(cwd).resolve()
    with _lock:
        _log.clear()
        _meta.update({"running": True, "cmd": " ".join(cmd), "started": time.time(), "exit_code": None})
        try:
            creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            _proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False,
                creationflags=creation,
            )
        except OSError as exc:
            _meta["running"] = False
            return f"Start failed: {exc}"
        proc = _proc

    def _reader() -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                with _lock:
                    _log.append(line)
                    if len(_log) > 500:
                        del _log[:100]
        except Exception:
            pass
        code = proc.wait()
        with _lock:
            _meta["running"] = False
            _meta["exit_code"] = code

    threading.Thread(target=_reader, daemon=True).start()
    return f"Started: {' '.join(cmd)}"


def detect_and_run(workspace: Path, path: str = "", debug: bool = False) -> str:
    ws = Path(workspace).resolve()
    path = (path or "").strip().replace("\\", "/")
    if path.endswith(".py"):
        py = ws / ".venv" / "Scripts" / "python.exe"
        exe = str(py) if py.is_file() else "python"
        script = str((ws / path).resolve())
        cwd = (ws / path).parent if "/" in path else ws
        if debug:
            return start([exe, "-X", "dev", "-u", script], cwd)
        return start([exe, script], cwd)
    if (ws / "package.json").is_file():
        npm = "npm.cmd" if os.name == "nt" else "npm"
        return start([npm, "run", "dev"], ws)
    if path.endswith((".js", ".mjs", ".cjs")):
        return start(["node", str((ws / path).resolve())], ws)
    if (ws / "pyproject.toml").is_file():
        py = ws / ".venv" / "Scripts" / "python.exe"
        exe = str(py) if py.is_file() else "python"
        if debug:
            return start([exe, "-m", "pytest", "-vv", "--tb=long"], ws)
        return start([exe, "-m", "pytest", "-q"], ws)
    return "No runnable project detected. Open a .py file or add package.json."
