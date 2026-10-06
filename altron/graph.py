from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from altron.adapters.catalog import openai_tools
from altron.adapters.identity_store import IdentityStore, extract_loose_facts
from altron.adapters.judge import critique
from altron.adapters.memory import JsonlMemory
from altron.adapters.think import ThinkAdapter, ThinkError
from altron.adapters.tools import parse_tool_directive, pick_action, run_tool
from altron.adapters.vector_memory import VectorMemory
from altron.adapters import dspy_compile, traces
from altron.identity import system_prompt
from altron.settings import Settings
from altron.state import AltronState

MAX_TOOL_ROUNDS = 2


class AltronCore:
    """LangGraph-shaped supervisor: remember -> plan -> think/act -> judge -> persist."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = JsonlMemory(settings.memory_path)
        self.vectors = VectorMemory(settings.vectors_path, qdrant_url=settings.qdrant_url)
        self.identity = IdentityStore(settings.identity_path)
        self.think = ThinkAdapter(settings)

    def run(self, messages: list[dict]) -> AltronState:
        state = self._blank(messages)
        state = self._remember(state)
        state = self._plan(state)
        if state.get("plan") == "act":
            state = self._act(state)
        else:
            state = self._think(state)
        return self._finish(state)

    def stream_turn(self, messages: list[dict]) -> Iterator[dict[str, Any]]:
        state = self._blank(messages)
        state = self._remember(state)
        state = self._plan(state)
        yield {
            "type": "meta",
            "plan": state.get("plan"),
            "trace": list(state.get("trace") or []),
            "memories": list(state.get("memories") or []),
        }
        if state.get("plan") == "act":
            state = self._act(state)
            state = self._finish(state)
            yield {"type": "token", "text": state.get("reply") or ""}
            yield {"type": "done", "state": state}
            return
        try:
            state = self._think(state)
            yield {"type": "token", "text": state.get("reply") or ""}
        except ThinkError as exc:
            text = f"ALTRON core is running, but Think is offline. {exc}"
            state["reply"] = text
            state["trace"] = [*(state.get("trace") or []), "think_error"]
            yield {"type": "token", "text": text}
        state = self._finish(state)
        yield {"type": "done", "state": state}

    def _blank(self, messages: list[dict]) -> AltronState:
        return {
            "messages": messages,
            "memories": [],
            "plan": "",
            "tool_name": "",
            "tool_args": {},
            "tool_result": "",
            "judgment": "",
            "reply": "",
            "backend": "",
            "trace": [],
        }

    def _user_text(self, state: AltronState) -> str:
        for message in reversed(state.get("messages") or []):
            if message.get("role") == "user":
                return str(message.get("content") or "")
        return ""

    def _prompt(self, state: AltronState) -> str:
        return system_prompt(
            state.get("memories") or [],
            self.identity.snapshot(),
            dspy_compile.compile_program(self.settings.traces_path),
        )

    def _remember(self, state: AltronState) -> AltronState:
        query = self._user_text(state)
        archival = self.memory.search(query)
        vector_hits = self.vectors.search(query, limit=8)
        core_facts = self.identity.all_facts()
        merged: list[str] = []
        for item in [*core_facts, *vector_hits, *archival]:
            if item not in merged:
                merged.append(item)
        state["memories"] = merged[:16]
        state["trace"] = [*(state.get("trace") or []), f"remember:{self.vectors.backend()}"]
        return state

    def _plan(self, state: AltronState) -> AltronState:
        picked = pick_action(self._user_text(state), self.settings)
        if picked:
            name, args = picked
            state["tool_name"] = name
            state["tool_args"] = args
            state["plan"] = "act"
        else:
            state["tool_name"] = ""
            state["tool_args"] = {}
            state["plan"] = "think"
        state["trace"] = [*(state.get("trace") or []), f"plan:{state['plan']}"]
        return state

    def _act(self, state: AltronState) -> AltronState:
        result = run_tool(
            state.get("tool_name") or "",
            self._user_text(state),
            self.memory,
            identity=self.identity,
            args=state.get("tool_args") or {},
            settings=self.settings,
            vectors=self.vectors,
        )
        state["tool_result"] = result
        state["reply"] = result
        state["backend"] = "tool"
        state["trace"] = [*(state.get("trace") or []), f"act:{state.get('tool_name')}"]
        return state

    def _think(self, state: AltronState) -> AltronState:
        payload = [
            {"role": "system", "content": self._prompt(state)},
            *(state.get("messages") or []),
        ]
        try:
            decision = self.think.decide(payload, tools=openai_tools())
        except ThinkError as exc:
            state["reply"] = f"ALTRON core is running, but Think is offline. {exc}"
            state["backend"] = "none"
            state["trace"] = [*(state.get("trace") or []), "think_error"]
            return state
        state["backend"] = decision.backend or "nvidia"
        calls = list(decision.tool_calls)
        if not calls:
            parsed = parse_tool_directive(decision.text)
            if parsed:
                calls = [parsed]
        if not calls:
            state["reply"] = decision.text
            state["trace"] = [*(state.get("trace") or []), f"think:{state['backend']}"]
            return state
        results: list[str] = []
        names: list[str] = []
        for call in calls[:MAX_TOOL_ROUNDS]:
            name = str(call.get("name") or "")
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            result = run_tool(
                name,
                self._user_text(state),
                self.memory,
                identity=self.identity,
                args=args,
                settings=self.settings,
                vectors=self.vectors,
            )
            names.append(name)
            results.append(f"{name}: {result}")
            state["trace"] = [*(state.get("trace") or []), f"act:{name}"]
        try:
            follow = self.think.complete(
                [
                    {"role": "system", "content": self._prompt(state)},
                    *(state.get("messages") or []),
                    {
                        "role": "user",
                        "content": "Tool results:\n" + "\n".join(results) + "\nAnswer the original request using these results. Do not emit TOOL lines.",
                    },
                ]
            )
            state["reply"] = follow
        except ThinkError:
            state["reply"] = "\n\n".join(results)
        state["tool_name"] = ",".join(names)
        state["tool_result"] = "\n".join(results)
        state["trace"] = [*(state.get("trace") or []), f"think:{state.get('backend')}"]
        return state

    def _finish(self, state: AltronState) -> AltronState:
        state = self._judge(state)
        return self._persist(state)

    def _judge(self, state: AltronState) -> AltronState:
        verdict = critique(self._user_text(state), state.get("reply") or "")
        state["judgment"] = verdict
        if verdict == "empty_reply":
            state["reply"] = "I did not produce an answer. Try again."
        state["trace"] = [*(state.get("trace") or []), f"judge:{verdict}"]
        return state

    def _persist(self, state: AltronState) -> AltronState:
        user_text = self._user_text(state)
        if user_text and state.get("plan") == "think":
            for block, fact in extract_loose_facts(user_text):
                self.identity.add_fact(fact, block=block)
                self.memory.write(fact, kind="fact")
                self.vectors.add(fact, kind="fact")
        traces.write(
            self.settings.traces_path,
            {
                "user": user_text,
                "reply": state.get("reply") or "",
                "judgment": state.get("judgment") or "",
                "plan": state.get("plan") or "",
                "backend": state.get("backend") or "",
                "trace": state.get("trace") or [],
            },
        )
        state["trace"] = [*(state.get("trace") or []), "persist"]
        return state
