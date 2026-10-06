from __future__ import annotations

from altron.identity import IDENTITY_NAME


def local_complete(messages: list[dict]) -> str:
    """Last-resort Think when NVIDIA and Ollama are both down."""
    user = ""
    system = ""
    for message in messages:
        role = message.get("role")
        if role == "system":
            system = str(message.get("content") or "")
        if role == "user":
            user = str(message.get("content") or "").strip()
    lowered = user.lower().strip().rstrip(".!?")
    in_ide = "altron ide" in system.lower() or "altron agent" in system.lower()

    if lowered in {"hi", "hello", "hey", "hai", "vanakkam"}:
        if in_ide:
            return (
                "Hello — I'm ALTRON Agent (free local fallback). "
                "Ask me to explain the open file, plan a change, or switch to Edit mode for diffs. "
                "For full reasoning, start Ollama (`ollama serve` + `ollama pull llama3.2`) "
                "or keep NVIDIA NIM keys in `.env`."
            )
        return f"Hello — I am {IDENTITY_NAME}. How can I help?"

    if any(mark in lowered for mark in ("who are you", "what are you", "your name")):
        return (
            f"I am {IDENTITY_NAME}, the AGI core of this workspace. "
            "NVIDIA Think and Ollama are offline, so this is the local fallback. "
            "Tools still work: list files, fetch, sandbox, PC control."
        )
    if "what can you do" in lowered or "what do you do" in lowered:
        return (
            f"{IDENTITY_NAME} can remember, judge, act on this Windows PC, "
            "read workspace files, fetch public pages, and run sandboxed Python. "
            "Start Ollama (`ollama serve` then `ollama pull llama3.2`) for a local LLM when NVIDIA is down."
        )
    if in_ide and user:
        return (
            f"{IDENTITY_NAME} Agent (free local fallback) heard: “{user[:200]}”. "
            "NVIDIA/Ollama are offline, so deep coding answers are limited. "
            "I can still help via IDE tools: open files in Explorer, Run ▶, Terminal, "
            "or Edit mode once a Think backend is up."
        )
    snippet = user[:160] if user else "that"
    return (
        f"{IDENTITY_NAME} local fallback: NVIDIA failed and Ollama is not running. "
        f"I cannot fully reason about “{snippet}” until a Think backend is up. "
        "I can still run allowlisted tools if you ask directly (list files, fetch a URL, run python …)."
    )
