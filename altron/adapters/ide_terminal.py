from __future__ import annotations

"""ALTRON IDE integrated terminal — real shell via pipes (Windows/Linux).

Not a fake console. Spawns PowerShell/cmd/bash in the workspace.
"""

import os
import subprocess
import threading
import uuid
from pathlib import Path

_sessions: dict[str, "TermSession"] = {}
_lock = threading.Lock()


class TermSession:
    def __init__(self, cwd: Path) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.cwd = Path(cwd).resolve()
        self.alive = True
        shell, args = _shell()
        creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            [shell, *args],
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

    def write(self, data: str) -> None:
        if not self.alive or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write(data)
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


def _shell() -> tuple[str, list[str]]:
    if os.name == "nt":
        return "powershell.exe", ["-NoLogo", "-NoExit"]
    for cand in ("bash", "sh"):
        return cand, []
    return "sh", []


def create(cwd: Path) -> TermSession:
    sess = TermSession(cwd)
    with _lock:
        _sessions[sess.id] = sess
    return sess


def get(sid: str) -> TermSession | None:
    with _lock:
        return _sessions.get(sid)


def kill(sid: str) -> str:
    with _lock:
        sess = _sessions.pop(sid, None)
    if not sess:
        return "No such terminal."
    sess.kill()
    return "Terminal killed."


def kill_all() -> None:
    with _lock:
        ids = list(_sessions.keys())
    for sid in ids:
        kill(sid)
