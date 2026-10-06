from __future__ import annotations

"""ALTRON IDE debugging — real breakpoints + step-through via stdlib pdb.

Not a fake "debug" flag. Spawns `python -m pdb <script>` in a pipe-connected
process (same primitive as ide_terminal.py), applies persisted breakpoints
before running, and exposes step/next/continue/print as plain pdb commands.
"""

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

_lock = threading.Lock()
_sessions: dict[str, "DebugSession"] = {}


class DebugSession:
    def __init__(self, script: Path, cwd: Path) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.script = script
        self.cwd = Path(cwd).resolve()
        self.alive = True
        py = self.cwd / ".venv" / "Scripts" / "python.exe"
        exe = str(py) if py.is_file() else sys.executable
        creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            [exe, "-u", "-m", "pdb", str(script)],
            cwd=str(self.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            shell=False,
            creationflags=creation,
        )
        self._q: list[str] = []
        self._q_lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        try:
            while self.alive and self.proc.poll() is None:
                chunk = self.proc.stdout.read(1)
                if not chunk:
                    break
                with self._q_lock:
                    self._q.append(chunk)
                    if len(self._q) > 200_000:
                        self._q = self._q[-100_000:]
        except Exception:
            pass
        self.alive = False

    def write(self, line: str) -> None:
        if not self.alive or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write(line.rstrip("\n") + "\n")
            self.proc.stdin.flush()
        except OSError:
            self.alive = False

    def read(self) -> str:
        with self._q_lock:
            if not self._q:
                return ""
            out = "".join(self._q)
            self._q.clear()
            return out

    def kill(self) -> None:
        self.alive = False
        try:
            if self.proc.poll() is None:
                self.proc.kill()
        except OSError:
            pass


def _bp_path(settings) -> Path:
    p = Path(settings.altron_data_dir) / "ide" / "breakpoints.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def list_breakpoints(settings) -> dict[str, list[int]]:
    path = _bp_path(settings)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def toggle_breakpoint(settings, file: str, line: int) -> dict[str, list[int]]:
    all_bp = list_breakpoints(settings)
    key = file.replace("\\", "/")
    lines = set(all_bp.get(key) or [])
    if line in lines:
        lines.discard(line)
    else:
        lines.add(line)
    if lines:
        all_bp[key] = sorted(lines)
    else:
        all_bp.pop(key, None)
    _bp_path(settings).write_text(json.dumps(all_bp, indent=2), encoding="utf-8")
    return all_bp


def start_debug(settings, workspace: Path, path: str) -> dict:
    ws = Path(workspace).resolve()
    script = (ws / path).resolve()
    if not script.is_file() or script.suffix != ".py":
        return {"ok": False, "message": "Debug only supports running a .py file"}
    sess = DebugSession(script, ws)
    with _lock:
        _sessions[sess.id] = sess
    # Apply persisted breakpoints for this file before letting it run.
    bp_lines = list_breakpoints(settings).get(path.replace("\\", "/"), [])
    for ln in bp_lines:
        sess.write(f"b {script}:{ln}")
    sess.write("c")  # run to first breakpoint (or exit if none hit)
    return {"ok": True, "id": sess.id, "breakpoints": bp_lines}


def command(session_id: str, action: str, expr: str = "") -> dict:
    sess = _sessions.get(session_id)
    if not sess or not sess.alive:
        return {"ok": False, "message": "No active debug session"}
    mapping = {"step": "s", "next": "n", "continue": "c", "quit": "q", "up": "u", "down": "d", "where": "w"}
    if action == "print":
        sess.write(f"p {expr}")
    elif action in mapping:
        sess.write(mapping[action])
    else:
        return {"ok": False, "message": f"Unknown debug action: {action}"}
    return {"ok": True}


def output(session_id: str) -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "data": "", "alive": False}
    return {"ok": True, "data": sess.read(), "alive": sess.alive}


def stop(session_id: str) -> dict:
    with _lock:
        sess = _sessions.pop(session_id, None)
    if not sess:
        return {"ok": False, "message": "No such debug session"}
    sess.kill()
    return {"ok": True, "message": "Debug session stopped"}
