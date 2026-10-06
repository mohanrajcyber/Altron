from __future__ import annotations

"""DSPy-shaped compile: turn judge traces into stronger prompt constraints."""

from pathlib import Path

from altron.adapters import traces


def compile_program(path: Path) -> str:
    base = traces.compile_hints(path, limit=40)
    rows = traces.recent(path, limit=40)
    fails = [r for r in rows if r.get("judgment") not in {"", "ok"}]
    backends = {}
    for r in rows:
        b = r.get("backend") or "unknown"
        backends[b] = backends.get(b, 0) + 1
    extra = []
    if fails:
        extra.append(f"- Seen {len(fails)} judged failures in last {len(rows)} turns.")
    if backends:
        mix = ", ".join(f"{k}:{v}" for k, v in sorted(backends.items()))
        extra.append(f"- Backend mix: {mix}.")
    if not base and not extra:
        return "No DSPy compile hints yet — need more judged turns."
    body = base or "Compiled from traces:"
    if extra:
        body = body + "\n" + "\n".join(extra)
    return body
