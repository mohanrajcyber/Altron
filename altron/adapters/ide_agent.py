from __future__ import annotations

"""ALTRON IDE organ — sticky workspace control (NO code-server / NO Copilot).

Real editor UI lives in the Face (Monaco). This module handles sticky commands
and filesystem helpers used by /api/ide/*.
"""

import json
import re
import subprocess
from pathlib import Path

from altron.adapters import computer, mcp_fs
from altron.adapters.workspace import resolve_allowed, DENY_NAMES, DENY_SUFFIXES

SKIP_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}


def open_ide(intent_path: Path, settings) -> str:
    ws = Path(settings.altron_workspace).resolve()
    sandbox = Path(settings.sandbox_path).resolve()
    sandbox.mkdir(parents=True, exist_ok=True)
    # Full ALTRON IDE page in a new browser tab (not Face iframe / not code-server).
    ide_url = f"http://{settings.altron_host}:{settings.altron_port}/ide"

    _set_intent(intent_path, "ide_control", workspace=str(ws), file="")
    try:
        computer.open_url(ide_url)
    except Exception:
        pass
    return (
        "ALTRON IDE opened in a new tab.\n"
        f"Workspace: {ws}\n"
        f"URL: {ide_url}\n"
        "\n"
        "This is ALTRON's own IDE — not VS Code / code-server / Copilot.\n"
        "\n"
        "Chat commands: list / open PATH / edit PATH ::: old >>> new /\n"
        "write name.txt ::: content / run python … / close ide"
    )


def act(user_text: str, intent_path: Path, settings) -> str:
    text = (user_text or "").strip()
    if not text:
        return "IDE listening — list · open … · edit … · run … · close ide"
    lowered = text.lower().strip().rstrip(".!?")

    if _wants_close(lowered):
        return close_ide(intent_path, settings)
    if lowered in {"status", "ide status"}:
        return status_message(settings, intent_path)
    if lowered in {"list", "ls", "dir", "list files", "show files"}:
        return list_files(intent_path, settings, ".")

    m = re.match(r"^(list|ls|dir)\s+(.+)$", text, flags=re.I)
    if m:
        return list_files(intent_path, settings, m.group(2).strip().strip("\"'"))

    m = re.match(r"^(open|read|show|cat|view)\s+(.+)$", text, flags=re.I)
    if m:
        return read_file(intent_path, settings, m.group(2).strip().strip("\"'"))

    m = re.match(r"^write\s+(.+?)\s*:::\s*(.+)$", text, flags=re.I | re.S)
    if m:
        return write_file(intent_path, settings, m.group(1).strip().strip("\"'"), m.group(2))

    m = re.match(r"^edit\s+(.+?)\s*:::\s*(.+?)\s*>>>\s*(.+)$", text, flags=re.I | re.S)
    if m:
        return edit_file(
            intent_path,
            settings,
            m.group(1).strip().strip("\"'"),
            m.group(2),
            m.group(3),
        )

    m = re.match(r"^run\s+file\s+(.+)$", text, flags=re.I)
    if m:
        return run_file(intent_path, settings, m.group(1).strip().strip("\"'"))

    if re.match(r"^run\s+python\b", lowered) or lowered.startswith("execute python"):
        code = re.sub(r"^(please\s+)?(run python|execute python)[:\s]*", "", text, flags=re.I)
        return run_python(intent_path, settings, code.strip(" `"))

    if lowered.startswith("run "):
        return run_python(intent_path, settings, text[4:].strip())

    if re.match(r"^[\w./\\-]+\.(py|md|txt|json|js|ts|css|html|toml|yaml|yml)$", text.strip()):
        return read_file(intent_path, settings, text.strip())

    return (
        "IDE is listening. Try:\n"
        "list · open altron/settings.py · "
        "edit file.py ::: old >>> new · "
        "run python print(1) · close ide"
    )


def close_ide(intent_path: Path, settings) -> str:
    clear_expect(intent_path)
    return "Closed ALTRON IDE control."


def expecting_control(intent_path: Path) -> bool:
    return _read_intent(intent_path).get("expect") == "ide_control"


def clear_expect(intent_path: Path) -> None:
    _set_intent(intent_path, "")


def status_message(settings, intent_path: Path) -> str:
    data = _read_intent(intent_path)
    cur = data.get("file") or "(none)"
    return (
        f"IDE sticky: on\n"
        f"Workspace: {settings.altron_workspace}\n"
        f"Current file: {cur}\n"
        f"UI: http://{settings.altron_host}:{settings.altron_port}/ide\n"
        "Engine: ALTRON Monaco (not code-server)"
    )


def probe(settings) -> dict:
    return {
        "running": True,
        "engine": "altron-monaco",
        "port": int(settings.altron_port),
        "url": f"http://{settings.altron_host}:{settings.altron_port}/ide",
        "workspace": str(Path(settings.altron_workspace).resolve()),
        "binary": "",
    }


def tree(settings, rel: str = ".", depth: int = 2) -> list[dict]:
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    target = resolve_allowed(rel or ".", roots, base=base) or base
    if not target.exists():
        return []
    return _walk(target, base, depth=max(0, min(depth, 4)))


def read_bytes(settings, rel: str) -> tuple[str | None, str]:
    roots = _roots(settings)
    base = Path(settings.altron_workspace)
    path = resolve_allowed(rel, roots, base=base)
    if path is None or not path.is_file():
        return None, f"Blocked or missing: {rel}"
    try:
        return path.read_text(encoding="utf-8"), ""
    except UnicodeDecodeError:
        return None, "Binary file"
    except OSError as exc:
        return None, str(exc)


def write_workspace(settings, rel: str, content: str, record_history: bool = True) -> str:
    """Write under workspace (not only sandbox) with secret path protection."""
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    path = resolve_allowed(rel, roots, base=base)
    if path is None:
        return f"Blocked path: {rel}"
    if path.name.lower() in {n.lower() for n in DENY_NAMES} or path.suffix.lower() in DENY_SUFFIXES:
        return f"Blocked secret/sensitive file: {rel}"
    before = ""
    if path.is_file():
        try:
            before = path.read_text(encoding="utf-8")
        except OSError:
            before = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"Write failed: {exc}"
    if record_history and before != content:
        try:
            from altron.adapters import ide_history

            ide_history.snapshot(settings, str(path.relative_to(base)).replace("\\", "/"), before, content, "write")
        except Exception:
            pass
    return f"Wrote {path} ({len(content)} chars)."


def move_path(settings, src: str, dst_dir: str) -> str:
    """Move file/folder into destination directory (or new path)."""
    src = (src or "").replace("\\", "/").strip("/")
    dst_dir = (dst_dir or "").replace("\\", "/").strip("/")
    name = Path(src).name
    if dst_dir.endswith(name):
        dst = dst_dir
    elif dst_dir in {".", ""}:
        dst = name
    else:
        dst = f"{dst_dir}/{name}"
    return rename_path(settings, src, dst)


def diagnose_file(settings, rel: str) -> list[dict]:
    """Lightweight static diagnostics (Problems panel)."""
    content, err = read_bytes(settings, rel)
    if content is None:
        return [{"severity": "error", "message": err or "cannot read", "line": 1, "path": rel}]
    issues: list[dict] = []
    ext = Path(rel).suffix.lower()
    lines = content.splitlines()
    if ext == ".py":
        for i, line in enumerate(lines, 1):
            if "\t" in line and line.lstrip().startswith(" "):
                issues.append({"severity": "warning", "message": "Mixed tabs/spaces", "line": i, "path": rel})
            if line.rstrip().endswith(":") and i < len(lines):
                nxt = lines[i] if i < len(lines) else ""
                # bare pass
            if "print " in line and not line.strip().startswith("#") and "print(" not in line:
                issues.append({"severity": "warning", "message": "Python 2 style print?", "line": i, "path": rel})
            if "TODO" in line or "FIXME" in line:
                issues.append({"severity": "info", "message": line.strip()[:80], "line": i, "path": rel})
        try:
            compile(content, rel, "exec")
        except SyntaxError as exc:
            issues.append(
                {
                    "severity": "error",
                    "message": f"SyntaxError: {exc.msg}",
                    "line": exc.lineno or 1,
                    "path": rel,
                }
            )
    elif ext in {".js", ".ts", ".tsx", ".jsx"}:
        for i, line in enumerate(lines, 1):
            if "console.log" in line:
                issues.append({"severity": "info", "message": "console.log left in code", "line": i, "path": rel})
            if "TODO" in line or "FIXME" in line:
                issues.append({"severity": "info", "message": line.strip()[:80], "line": i, "path": rel})
    else:
        for i, line in enumerate(lines, 1):
            if "TODO" in line or "FIXME" in line:
                issues.append({"severity": "info", "message": line.strip()[:80], "line": i, "path": rel})
    return issues[:50]


def create_path(settings, rel: str, kind: str = "file") -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    path = resolve_allowed(rel, roots, base=base)
    if path is None:
        # allow creating new paths under workspace
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return f"Blocked path: {rel}"
        path = candidate
    if path.exists():
        return f"Already exists: {rel}"
    try:
        if kind == "dir":
            path.mkdir(parents=True, exist_ok=False)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
    except OSError as exc:
        return f"Create failed: {exc}"
    return f"Created {kind}: {rel}"


def rename_path(settings, src: str, dst: str) -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    a = resolve_allowed(src, roots, base=base)
    b_cand = (base / dst).resolve()
    try:
        b_cand.relative_to(base)
    except ValueError:
        return f"Blocked destination: {dst}"
    if a is None or not a.exists():
        return f"Missing: {src}"
    if b_cand.exists():
        return f"Destination exists: {dst}"
    try:
        b_cand.parent.mkdir(parents=True, exist_ok=True)
        a.rename(b_cand)
    except OSError as exc:
        return f"Rename failed: {exc}"
    return f"Renamed {src} → {dst}"


def delete_path(settings, rel: str) -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    path = resolve_allowed(rel, roots, base=base)
    if path is None or not path.exists():
        return f"Missing or blocked: {rel}"
    if path == base:
        return "Refusing to delete workspace root."
    try:
        if path.is_dir():
            import shutil

            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        return f"Delete failed: {exc}"
    return f"Deleted {rel}"


def search_files(settings, query: str, max_hits: int = 40) -> list[dict]:
    """Filename + content search (ripgrep when available, else Python scan)."""
    q = (query or "").strip()
    if not q:
        return []
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    rg_hits = _search_ripgrep(roots, base, q, max_hits)
    if rg_hits is not None:
        return rg_hits
    return _search_python(roots, base, q.lower(), max_hits)


def _search_ripgrep(roots: list[Path], base: Path, query: str, max_hits: int) -> list[dict] | None:
    import shutil

    rg = shutil.which("rg")
    if not rg:
        return None
    hits: list[dict] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            proc = subprocess.run(
                [
                    rg,
                    "--json",
                    "--max-count",
                    "3",
                    "-g",
                    "!**/.venv/**",
                    "-g",
                    "!**/node_modules/**",
                    "-g",
                    "!**/.git/**",
                    query,
                    str(root),
                ],
                capture_output=True,
                text=True,
                timeout=12,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        for line in (proc.stdout or "").splitlines():
            if len(hits) >= max_hits:
                return hits
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "match":
                continue
            data = ev.get("data") or {}
            path_text = ((data.get("path") or {}).get("text")) or ""
            try:
                abs_p = Path(path_text).resolve()
                try:
                    rel = str(abs_p.relative_to(base)).replace("\\", "/")
                except ValueError:
                    rel = str(abs_p).replace("\\", "/")
            except OSError:
                rel = path_text.replace("\\", "/")
            ln = (data.get("line_number") or 1)
            lines = data.get("lines") or {}
            snippet = (lines.get("text") or "").strip()[:160]
            hits.append(
                {
                    "path": rel,
                    "name": Path(rel).name,
                    "via": "rg",
                    "line": ln,
                    "snippet": snippet,
                }
            )
    return hits


def _search_python(roots: list[Path], base: Path, q: str, max_hits: int) -> list[dict]:
    hits: list[dict] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if len(hits) >= max_hits:
                return hits
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            rel_parts = path.parts[len(root.parts) :]
            if any(p.startswith(".") and p not in {".env.example"} for p in rel_parts):
                continue
            try:
                try:
                    rel = str(path.relative_to(base)).replace("\\", "/")
                except ValueError:
                    rel = str(path.resolve()).replace("\\", "/")
            except OSError:
                continue
            name_hit = q in path.name.lower()
            content_hit = False
            snippet = ""
            line_no = 1
            if not name_hit and path.suffix.lower() in {
                ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".yml", ".yaml",
                ".toml", ".css", ".html", ".txt", ".ps1", ".sql",
            }:
                try:
                    if path.stat().st_size > 200_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                idx = text.lower().find(q)
                if idx >= 0:
                    content_hit = True
                    line_no = text.count("\n", 0, idx) + 1
                    lo = max(0, idx - 40)
                    hi = min(len(text), idx + len(q) + 40)
                    snippet = text[lo:hi].replace("\n", " ")
            if name_hit or content_hit:
                hits.append(
                    {
                        "path": rel,
                        "name": path.name,
                        "via": "name" if name_hit else "content",
                        "line": line_no,
                        "snippet": snippet,
                    }
                )
    return hits


def find_symbol(settings, symbol: str, path: str = "") -> list[dict]:
    """Light Python def/class lookup for hover + go-to."""
    name = (symbol or "").strip()
    if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return []
    roots = _roots(settings)
    base = Path(settings.altron_workspace).resolve()
    pat = re.compile(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b")
    hits: list[dict] = []
    scan: list[Path] = []
    if path:
        p = resolve_allowed(path, roots, base=base)
        if p and p.is_file():
            scan = [p]
    if not scan:
        for root in roots:
            if not root.is_dir():
                continue
            for fp in root.rglob("*.py"):
                if any(part in SKIP_DIR_NAMES for part in fp.parts):
                    continue
                scan.append(fp)
                if len(scan) >= 200:
                    break
            if len(scan) >= 200:
                break
    for fp in scan:
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            try:
                rel = str(fp.relative_to(base)).replace("\\", "/")
            except ValueError:
                rel = str(fp.resolve()).replace("\\", "/")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                hits.append({"path": rel, "line": i, "text": line.strip()[:120], "symbol": name})
                if len(hits) >= 20:
                    return hits
    return hits


def hover_at(settings, path: str, line: int, column: int = 1) -> dict:
    """Return hover info for word at line/col (1-based)."""
    content, err = read_bytes(settings, path)
    if content is None:
        return {"ok": False, "error": err or "missing"}
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return {"ok": True, "contents": ""}
    row = lines[line - 1]
    col = max(1, min(column, len(row) + 1)) - 1
    # expand word
    i = col
    while i > 0 and (row[i - 1].isalnum() or row[i - 1] == "_"):
        i -= 1
    j = col
    while j < len(row) and (row[j].isalnum() or row[j] == "_"):
        j += 1
    word = row[i:j]
    if not word:
        return {"ok": True, "contents": "", "symbol": ""}
    defs = find_symbol(settings, word, path)
    if defs:
        d0 = defs[0]
        return {
            "ok": True,
            "symbol": word,
            "contents": f"**{word}**\n\n`{d0['path']}:{d0['line']}`\n```python\n{d0['text']}\n```",
            "defs": defs,
        }
    return {"ok": True, "symbol": word, "contents": f"`{word}`", "defs": []}


def tree_multi(settings, depth: int = 1) -> list[dict]:
    """Multi-root explorer sections."""
    base = Path(settings.altron_workspace).resolve()
    sections: list[dict] = [
        {
            "id": "main",
            "label": base.name or "ALTRON",
            "path": str(base),
            "rel": ".",
            "items": tree(settings, ".", depth=depth),
        }
    ]
    for i, root in enumerate(_extra_roots(settings)):
        if root == base:
            continue
        items = _walk(root, root, depth=max(0, min(depth, 4)))
        sections.append(
            {
                "id": f"extra{i}",
                "label": root.name or f"root{i}",
                "path": str(root),
                "rel": str(root),
                "items": _absolutize_tree(items, root),
            }
        )
    return sections


def _absolutize_tree(items: list[dict], root: Path) -> list[dict]:
    out: list[dict] = []
    for n in items:
        node = dict(n)
        try:
            node["path"] = str((root / n["path"]).resolve()).replace("\\", "/")
        except (OSError, KeyError):
            pass
        if n.get("children"):
            node["children"] = _absolutize_tree(n["children"], root)
        out.append(node)
    return out


def flat_files(settings, max_n: int = 400) -> list[str]:
    base = Path(settings.altron_workspace).resolve()
    out: list[str] = []
    for path in base.rglob("*"):
        if len(out) >= max_n:
            break
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        rel_parts = path.parts[len(base.parts) :]
        if any(p.startswith(".") and p not in {".env.example", ".continue"} for p in rel_parts):
            continue
        try:
            out.append(str(path.relative_to(base)).replace("\\", "/"))
        except ValueError:
            continue
    return out


def apply_edit(settings, rel: str, old: str, new: str) -> str:
    return edit_file(Path(settings.intent_path), settings, rel, old, new)


def parse_agent_diffs(text: str) -> list[dict]:
    """Parse ALTRON_DIFF blocks from agent replies."""
    import re

    diffs: list[dict] = []
    pattern = re.compile(
        r"ALTRON_DIFF\s+path=(.+?)\n<<<<<<<\s*OLD\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*NEW",
        re.S | re.I,
    )
    for m in pattern.finditer(text or ""):
        diffs.append(
            {
                "path": m.group(1).strip(),
                "old": m.group(2),
                "new": m.group(3),
            }
        )
    return diffs


def list_files(intent_path: Path, settings, rel: str) -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace)
    msg = mcp_fs.fs_list(rel or ".", roots, base)
    _touch(intent_path, settings)
    return "ALTRON IDE · files\n" + msg


def read_file(intent_path: Path, settings, rel: str) -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace)
    msg = mcp_fs.fs_read(rel, roots, base)
    _set_intent(intent_path, "ide_control", workspace=str(base), file=rel)
    return "ALTRON IDE · file\n" + msg


def write_file(intent_path: Path, settings, rel: str, content: str) -> str:
    msg = write_workspace(settings, rel, content)
    _set_intent(intent_path, "ide_control", workspace=str(settings.altron_workspace), file=rel)
    return "ALTRON IDE · wrote\n" + msg


def edit_file(intent_path: Path, settings, rel: str, old: str, new: str) -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace)
    path = resolve_allowed(rel, roots, base=base)
    if path is None or not path.is_file():
        return f"Edit blocked or missing: {rel}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Cannot read: {exc}"
    if old not in text:
        return "old string not found — edit aborted (no change)."
    if text.count(old) > 1:
        return "old string matches multiple places — make it unique."
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    _set_intent(intent_path, "ide_control", workspace=str(base), file=str(path))
    return f"Edited {path} (1 replacement)."


def run_python(intent_path: Path, settings, code: str) -> str:
    code = (code or "").strip()
    if not code:
        return "What Python should I run?"
    sandbox = Path(settings.sandbox_path).resolve()
    sandbox.mkdir(parents=True, exist_ok=True)
    script = sandbox / "_ide_run.py"
    script.write_text(code + "\n", encoding="utf-8")
    return _exec_python(script, sandbox, intent_path, settings)


def run_file(intent_path: Path, settings, rel: str) -> str:
    roots = _roots(settings)
    base = Path(settings.altron_workspace)
    path = resolve_allowed(rel, roots, base=base)
    if path is None or not path.is_file():
        return f"Cannot run: {rel}"
    if path.suffix.lower() != ".py":
        return "Only .py files are runnable in IDE v1."
    return _exec_python(path.resolve(), path.parent, intent_path, settings)


def _exec_python(script: Path, cwd: Path, intent_path: Path, settings) -> str:
    py = Path(settings.altron_workspace).resolve() / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else "python"
    script = Path(script).resolve()
    cwd = Path(cwd).resolve()
    try:
        proc = subprocess.run(
            [exe, str(script)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=45,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return "Run timed out (45s)."
    except OSError as exc:
        return f"Run failed: {exc}"
    out = (proc.stdout or "")[-4000:]
    err = (proc.stderr or "")[-2000:]
    _touch(intent_path, settings)
    status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
    parts = [f"ALTRON IDE · run ({status})", out.strip() or "(no stdout)"]
    if err.strip():
        parts.append("stderr:\n" + err.strip())
    return "\n".join(parts)


def _walk(path: Path, base: Path, depth: int) -> list[dict]:
    items: list[dict] = []
    try:
        children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return items
    for child in children:
        if child.name.startswith(".") and child.name not in {".continue", ".env.example"}:
            if child.name in {".venv", ".git", ".pytest_cache"}:
                continue
        if child.name in SKIP_DIR_NAMES:
            continue
        try:
            rel = str(child.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
        node = {"name": child.name, "path": rel, "type": "dir" if child.is_dir() else "file"}
        if child.is_dir() and depth > 0:
            node["children"] = _walk(child, base, depth - 1)
        items.append(node)
        if len(items) >= 80:
            break
    return items


def _extra_roots(settings) -> list[Path]:
    """Valid absolute extra roots from ide prefs."""
    try:
        prefs = Path(settings.altron_data_dir) / "ide" / "prefs.json"
        if not prefs.is_file():
            return []
        data = json.loads(prefs.read_text(encoding="utf-8"))
        raw = data.get("extra_roots") or []
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    out: list[Path] = []
    for item in raw:
        try:
            p = Path(str(item)).expanduser().resolve()
        except OSError:
            continue
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def _roots(settings) -> list[Path]:
    roots = [Path(settings.altron_workspace).resolve(), Path(settings.sandbox_path).resolve()]
    for extra in _extra_roots(settings):
        if extra not in roots:
            roots.append(extra)
    return roots


def _wants_close(lowered: str) -> bool:
    return bool(
        re.search(r"\b(close|exit|quit|stop)\b.+\bide\b", lowered)
        or lowered in {"close ide", "exit ide", "stop ide"}
    )


def _touch(intent_path: Path, settings) -> None:
    data = _read_intent(intent_path)
    _set_intent(
        intent_path,
        "ide_control",
        workspace=str(settings.altron_workspace),
        file=data.get("file") or "",
    )


def _set_intent(path: Path, expect: str, workspace: str = "", file: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"expect": expect}
    if workspace:
        data["workspace"] = workspace
    if file:
        data["file"] = file
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_intent(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
