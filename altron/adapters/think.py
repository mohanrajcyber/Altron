from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

from openai import OpenAI, APIStatusError

from altron.adapters.local_think import local_complete
from altron.adapters.ollama import ollama_base, pick_model, probe
from altron.settings import Settings


class ThinkError(RuntimeError):
    pass


@dataclass
class ThinkDecision:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    backend: str = "nvidia"


class ThinkAdapter:
    """NVIDIA NIM first, then Ollama, then local stub. Harvested from LiteLLM + pydantic-ai OllamaProvider."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def complete(self, messages: list[dict], model: str | None = None) -> str:
        return "".join(self.stream(messages, model=model))

    def decide(self, messages: list[dict], tools: list[dict] | None = None) -> ThinkDecision:
        last_error: Exception | None = None
        if self.settings.api_keys:
            try:
                return self._nvidia_decide(messages, tools)
            except Exception as exc:  # noqa: BLE001 — fall through to Ollama
                last_error = exc
        ollama = probe(self.settings)
        if ollama.get("ok"):
            try:
                return self._ollama_decide(messages, tools, ollama.get("models") or [])
            except Exception as exc:  # noqa: BLE001 — fall through to local
                last_error = exc
        stub = local_complete(messages)
        if last_error:
            return ThinkDecision(text=stub, backend="local")
        return ThinkDecision(text=stub, backend="local")

    def stream(self, messages: list[dict], model: str | None = None) -> Iterator[str]:
        last_error: Exception | None = None
        if self.settings.api_keys:
            try:
                yield from self._nvidia_stream(messages, model=model)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        ollama = probe(self.settings)
        if ollama.get("ok"):
            try:
                yield from self._ollama_stream(messages, ollama.get("models") or [])
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        yield local_complete(messages)
        if last_error:
            return

    def _nvidia_client(self, key: str) -> OpenAI:
        return OpenAI(
            api_key=key,
            base_url=self.settings.nvidia_nim_api_base.rstrip("/"),
            timeout=self.settings.altron_timeout_seconds,
            max_retries=self.settings.altron_max_retries,
        )

    def _ollama_client(self) -> OpenAI:
        return OpenAI(
            api_key="ollama",
            base_url=ollama_base(self.settings),
            timeout=min(self.settings.altron_timeout_seconds, 45.0),
            max_retries=0,
        )

    def _nvidia_decide(self, messages: list[dict], tools: list[dict] | None) -> ThinkDecision:
        last_error: Exception | None = None
        models = [self.settings.altron_model, self.settings.altron_fallback_model]
        seen: list[str] = []
        for candidate in models:
            if not candidate or candidate in seen:
                continue
            seen.append(candidate)
            for key in self.settings.api_keys:
                try:
                    decision = self._decide_one(self._nvidia_client(key), candidate, messages, tools)
                    decision.backend = "nvidia"
                    return decision
                except APIStatusError as exc:
                    last_error = exc
                    if exc.status_code in {400, 401, 403, 404, 410, 429, 503}:
                        continue
                    raise ThinkError(f"NVIDIA NIM failed ({exc.status_code}): {exc}") from exc
                except ThinkError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue
        raise ThinkError(f"All NVIDIA keys/models failed: {last_error}")

    def _nvidia_stream(self, messages: list[dict], model: str | None = None) -> Iterator[str]:
        last_error: Exception | None = None
        models = [model or self.settings.altron_model, self.settings.altron_fallback_model]
        seen: list[str] = []
        for candidate in models:
            if not candidate or candidate in seen:
                continue
            seen.append(candidate)
            for key in self.settings.api_keys:
                try:
                    yield from self._stream_one(self._nvidia_client(key), candidate, messages)
                    return
                except APIStatusError as exc:
                    last_error = exc
                    if exc.status_code in {400, 401, 403, 404, 410, 429, 503}:
                        continue
                    raise ThinkError(f"NVIDIA NIM failed ({exc.status_code}): {exc}") from exc
                except ThinkError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue
        raise ThinkError(f"All NVIDIA keys/models failed: {last_error}")

    def _ollama_decide(self, messages: list[dict], tools: list[dict] | None, available: list[str]) -> ThinkDecision:
        model = pick_model(self.settings, available)
        decision = self._decide_one(self._ollama_client(), model, messages, tools)
        decision.backend = "ollama"
        return decision

    def _ollama_stream(self, messages: list[dict], available: list[str]) -> Iterator[str]:
        model = pick_model(self.settings, available)
        yield from self._stream_one(self._ollama_client(), model, messages)

    def _decide_one(self, client: OpenAI, model: str, messages: list[dict], tools: list[dict] | None) -> ThinkDecision:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0.4,
            "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = client.chat.completions.create(**kwargs)
        except APIStatusError:
            if tools:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.4,
                    stream=False,
                )
            else:
                raise
        choice = (response.choices or [None])[0]
        if choice is None:
            raise ThinkError(f"Empty completion from {model}")
        message = choice.message
        calls = []
        for call in getattr(message, "tool_calls", None) or []:
            fn = getattr(call, "function", None)
            name = getattr(fn, "name", "") if fn else ""
            raw_args = getattr(fn, "arguments", "") if fn else ""
            try:
                parsed = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            calls.append(
                {
                    "id": getattr(call, "id", "") or f"call_{len(calls)+1}",
                    "name": name,
                    "arguments": parsed,
                }
            )
        if calls:
            return ThinkDecision(tool_calls=calls)
        return ThinkDecision(text=(message.content or "").strip())

    def _stream_one(self, client: OpenAI, model: str, messages: list[dict]) -> Iterator[str]:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            stream=True,
        )
        got = False
        for event in stream:
            choices = getattr(event, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta else None
            if text:
                got = True
                yield text
        if not got:
            raise ThinkError(f"Empty stream from {model}")
