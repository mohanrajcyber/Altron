from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def write(path: Path, record: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": (record.get("user") or "")[:500],
        "reply": (record.get("reply") or "")[:1500],
        "judgment": record.get("judgment") or "",
        "plan": record.get("plan") or "",
        "backend": record.get("backend") or "",
        "trace": list(record.get("trace") or [])[-16:],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def recent(path: Path, limit: int = 16) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(rows[-limit:]))


def compile_hints(path: Path, limit: int = 20) -> str:
    """DSPy-shaped compile: turn judge failures into prompt constraints."""
    fails = [row for row in recent(path, limit=limit) if row.get("judgment") not in {"", "ok"}]
    if not fails:
        return ""
    lines = []
    seen: set[str] = set()
    for row in fails[:6]:
        verdict = str(row.get("judgment") or "")
        if verdict in seen:
            continue
        seen.add(verdict)
        lines.append(f"- Do not repeat judge failure `{verdict}`.")
    if "possible_secret_leak" in seen:
        lines.append("- Never echo API keys or nvapi- secrets.")
    if "stock_disclaimer" in seen:
        lines.append("- Never say you are a generic AI language model.")
    if "echo" in seen:
        lines.append("- Do not repeat the user message verbatim.")
    return "Compiled from traces:\n" + "\n".join(lines)
