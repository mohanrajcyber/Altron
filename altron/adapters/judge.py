import re


def critique(user_text: str, reply: str) -> str:
    """Lightweight guardrail pass. Future AGI traces replace this later."""
    if not reply.strip():
        return "empty_reply"
    lowered = reply.lower()
    if "as an ai language model" in lowered:
        return "stock_disclaimer"
    if len(reply) > 12000:
        return "too_long"
    if _looks_like_secret(reply):
        return "possible_secret_leak"
    if user_text.strip() and reply.strip() == user_text.strip():
        return "echo"
    return "ok"


def _looks_like_secret(text: str) -> bool:
    return bool(re.search(r"nvapi-[A-Za-z0-9_-]{20,}", text))
