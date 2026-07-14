"""Normalized local OpenAI-compatible chat client."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from openai import OpenAI

ReasoningLevel = Literal["off", "low", "medium", "high", "unlimited"]
ModelEventHandler = Callable[[str, dict[str, Any]], None]
REASONING_BUDGETS: dict[ReasoningLevel, int] = {
    "off": 0,
    "low": 512,
    "medium": 1536,
    "high": 3072,
    "unlimited": -1,
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class AssistantMessage:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None

    def as_history_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.reasoning_content is not None:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


class ModelClient(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage: ...


class LocalLlamaClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        reasoning_level: ReasoningLevel = "medium",
        event_handler: ModelEventHandler | None = None,
    ):
        self.client = OpenAI(base_url=base_url, api_key=api_key or "local-no-auth")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_level = reasoning_level
        self.event_handler = event_handler

    def set_event_handler(self, handler: ModelEventHandler | None) -> None:
        self.event_handler = handler

    def _emit(self, event: str, **data: Any) -> None:
        if self.event_handler is not None:
            self.event_handler(event, data)

    def set_reasoning_level(self, level: ReasoningLevel) -> None:
        if level not in REASONING_BUDGETS:
            raise ValueError(f"Unknown reasoning level: {level}")
        self.reasoning_level = level

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra_body": {
                "thinking_budget_tokens": REASONING_BUDGETS[self.reasoning_level],
            },
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = tools
            request["parallel_tool_calls"] = False
        response = self.client.chat.completions.create(**request)
        return self._consume_stream(response)

    def _consume_stream(self, response: Iterable[Any]) -> AssistantMessage:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        call_parts: dict[int, dict[str, str]] = {}
        actual_completion_tokens: int | None = None
        content_characters = 0
        reasoning_characters = 0
        self._emit("generation_start")
        for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None and getattr(usage, "completion_tokens", None) is not None:
                actual_completion_tokens = int(usage.completion_tokens)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            content = getattr(delta, "content", None) or ""
            extra = getattr(delta, "model_extra", None) or {}
            reasoning = (
                extra.get("reasoning_content") or getattr(delta, "reasoning_content", None) or ""
            )
            if content:
                content_parts.append(content)
                content_characters += len(content)
            if reasoning:
                reasoning_parts.append(reasoning)
                reasoning_characters += len(reasoning)
            for item in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(item, "index", 0) or 0)
                aggregate = call_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if getattr(item, "id", None):
                    aggregate["id"] = item.id
                function = getattr(item, "function", None)
                if function is not None:
                    aggregate["name"] += getattr(function, "name", None) or ""
                    aggregate["arguments"] += getattr(function, "arguments", None) or ""
            characters = content_characters + reasoning_characters
            self._emit(
                "generation_progress",
                completion_tokens_estimate=max(1, characters // 4),
                content_characters=content_characters,
                reasoning_characters=reasoning_characters,
            )
        estimated_tokens = max(
            1,
            (content_characters + reasoning_characters) // 4,
        )
        completion_tokens = actual_completion_tokens or estimated_tokens
        self._emit(
            "generation_complete",
            completion_tokens=completion_tokens,
            exact=actual_completion_tokens is not None,
        )
        calls = [
            ToolCall(
                id=value["id"] or f"stream-call-{index}",
                name=value["name"],
                arguments=value["arguments"] or "{}",
            )
            for index, value in sorted(call_parts.items())
            if value["name"]
        ]
        return AssistantMessage(
            content="".join(content_parts) or None,
            tool_calls=calls,
            reasoning_content="".join(reasoning_parts) or None,
        )
