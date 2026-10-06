from __future__ import annotations

import subprocess
from pathlib import Path

from altron.adapters.workspace import resolve_allowed


def git_status(path: str, roots: list[Path], base: Path) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    return _run(repo, ["status", "-sb", "--untracked-files=all"])


def git_status_porcelain(path: str, roots: list[Path], base: Path) -> dict:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return {"ok": False, "error": repo, "branch": "", "entries": []}
    raw = _run(repo, ["status", "--porcelain=v1", "-b"])
    branch = ""
    entries: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("##"):
            branch = line[2:].strip()
            continue
        if len(line) < 4:
            continue
        xy, name = line[:2], line[3:]
        if " -> " in name:
            name = name.split(" -> ", 1)[-1]
        staged = xy[0] not in (" ", "?")
        unstaged = xy[1] not in (" ",)
        entries.append({"path": name, "xy": xy, "staged": staged, "unstaged": unstaged or xy == "??"})
    return {"ok": True, "branch": branch, "entries": entries, "repo": str(repo)}


def git_log(path: str, roots: list[Path], base: Path, count: int = 8) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    n = max(1, min(int(count or 8), 20))
    return _run(repo, ["log", "-n", str(n), "--oneline"])


def git_diff(path: str, roots: list[Path], base: Path, file: str = "", staged: bool = False) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    args = ["diff", "--staged"] if staged else ["diff"]
    if file.strip():
        args.extend(["--", file.strip()])
    return _run(repo, args)


def git_stage(path: str, roots: list[Path], base: Path, files: list[str]) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    if not files:
        return _run(repo, ["add", "-A"])
    return _run(repo, ["add", "--", *files])


def git_unstage(path: str, roots: list[Path], base: Path, files: list[str]) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    if not files:
        return _run(repo, ["restore", "--staged", "."])
    return _run(repo, ["restore", "--staged", "--", *files])


def git_commit(path: str, roots: list[Path], base: Path, message: str) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    msg = (message or "").strip()
    if not msg:
        return "Commit message required."
    return _run(repo, ["commit", "-m", msg])


def git_pull(path: str, roots: list[Path], base: Path) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    return _run(repo, ["pull", "--ff-only"], timeout=60)


def git_push(path: str, roots: list[Path], base: Path) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    return _run(repo, ["push"], timeout=60)


def git_branches(path: str, roots: list[Path], base: Path) -> dict:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return {"ok": False, "error": repo, "branches": [], "current": ""}
    raw = _run(repo, ["branch", "--list"])
    branches: list[str] = []
    current = ""
    for line in raw.splitlines():
        name = line.strip()
        if not name:
            continue
        if name.startswith("* "):
            current = name[2:].strip()
            branches.append(current)
        else:
            branches.append(name.lstrip("* ").strip())
    return {"ok": True, "branches": branches, "current": current}


def git_checkout(path: str, roots: list[Path], base: Path, branch: str) -> str:
    repo = _repo(path, roots, base)
    if isinstance(repo, str):
        return repo
    br = (branch or "").strip()
    if not br or any(c in br for c in " ;|&"):
        return "Invalid branch name."
    return _run(repo, ["checkout", br])


def _repo(path: str, roots: list[Path], base: Path) -> Path | str:
    target = resolve_allowed(path or ".", roots, base=base)
    if target is None:
        # allow repo root even when resolve denies .git internals
        probe = (base / (path or ".")).resolve()
        try:
            probe.relative_to(base.resolve())
        except ValueError:
            return "Blocked: repo path is outside the ALTRON workspace."
        target = probe if probe.is_dir() else probe.parent
    probe = target if target.is_dir() else target.parent
    # walk up for .git
    cur = probe
    for _ in range(8):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return f"No git repo at {probe}."


def _run(repo: Path, args: list[str], timeout: int = 20) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git failed: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return err or out or f"git exit {proc.returncode}"
    return out or err or "(ok)"
