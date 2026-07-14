"""Normalized local OpenAI-compatible chat client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI


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
    ):
        self.client = OpenAI(base_url=base_url, api_key=api_key or "local-no-auth")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantMessage:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            request["tools"] = tools
            request["parallel_tool_calls"] = False
        response = self.client.chat.completions.create(**request)
        raw = response.choices[0].message
        extra = raw.model_extra or {}
        reasoning = extra.get("reasoning_content") or getattr(raw, "reasoning_content", None)
        calls: list[ToolCall] = []
        for item in raw.tool_calls or []:
            function = getattr(item, "function", None)
            if function is not None:
                calls.append(ToolCall(id=item.id, name=function.name, arguments=function.arguments))
        return AssistantMessage(content=raw.content, tool_calls=calls, reasoning_content=reasoning)
