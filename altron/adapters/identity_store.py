from __future__ import annotations

import json
from pathlib import Path

BLOCKS = ("human", "workspace")


class IdentityStore:
    """Letta-style core memory blocks. Survives process restart."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save({"human": [], "workspace": []})

    def load(self) -> dict[str, list[str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        return {block: list(raw.get(block) or []) for block in BLOCKS}

    def save(self, data: dict[str, list[str]]) -> None:
        clean = {block: list(data.get(block) or [])[:40] for block in BLOCKS}
        self.path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_fact(self, text: str, block: str = "workspace") -> bool:
        fact = text.strip()
        if not fact:
            return False
        if block not in BLOCKS:
            block = "workspace"
        data = self.load()
        if fact in data[block]:
            return False
        data[block].append(fact)
        self.save(data)
        return True

    def all_facts(self) -> list[str]:
        data = self.load()
        return [*(data["workspace"]), *(data["human"])]

    def snapshot(self) -> dict[str, list[str]]:
        return self.load()


def classify_block(text: str) -> str:
    lowered = text.lower()
    human_marks = ("my name", "i am ", "i'm ", "i like", "i prefer", "call me", "i work")
    if any(mark in lowered for mark in human_marks):
        return "human"
    return "workspace"


def extract_loose_facts(user_text: str) -> list[tuple[str, str]]:
    text = user_text.strip()
    lowered = text.lower()
    if not text or lowered.startswith(("who ", "what ", "how ", "why ", "when ")):
        return []
    marks = ("my name is", "call me ", "i like ", "i prefer ", "i work on")
    if any(mark in lowered for mark in marks):
        return [(classify_block(text), text)]
    return []
