from typing import Any, TypedDict


class ChatMessage(TypedDict, total=False):
    role: str
    content: str


class AltronState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    memories: list[str]
    plan: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: str
    judgment: str
    reply: str
    backend: str
    trace: list[str]
