from __future__ import annotations

from pathlib import Path

DENY_NAMES = {".env", ".venv", "api.txt", ".git"}
DENY_SUFFIXES = {".pem", ".key", ".pfx"}
MAX_READ_BYTES = 64_000
MAX_WRITE_BYTES = 32_000
MAX_LIST = 200


def resolve_allowed(raw: str, roots: list[Path], base: Path | None = None) -> Path | None:
    if not raw or "\x00" in raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (base or roots[0]) / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if _denied(resolved):
        return None
    for root in roots:
        try:
            root_r = root.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root_r)
            return resolved
        except ValueError:
            continue
    return None


def _denied(path: Path) -> bool:
    names = {part.lower() for part in path.parts}
    if names & {n.lower() for n in DENY_NAMES}:
        return True
    if path.name.lower() in {".env", "api.txt"}:
        return True
    if path.suffix.lower() in DENY_SUFFIXES:
        return True
    return False


def workspace_roots(root: Path) -> list[Path]:
    return [root.resolve()]
