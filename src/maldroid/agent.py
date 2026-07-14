"""Bounded local-model conversation and tool-calling loop."""

from __future__ import annotations

import json
from typing import Any

from maldroid.case_manager import Case
from maldroid.config import AppConfig
from maldroid.llama_client import ModelClient
from maldroid.prompts import SYSTEM_PROMPT, profile_prompt
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolExecutor
from maldroid.tools.registry import ToolRegistry


class MalDroidAgent:
    def __init__(
        self,
        config: AppConfig,
        case: Case,
        client: ModelClient,
        registry: ToolRegistry,
        dispatcher: ToolExecutor,
        sessions: SessionManager,
        previous_summary: str = "",
    ):
        self.config = config
        self.case = case
        self.client = client
        self.registry = registry
        self.dispatcher = dispatcher
        self.sessions = sessions
        self.messages: list[dict[str, Any]] = []
        self._reset_messages(previous_summary)

    def _reset_messages(self, summary: str = "") -> None:
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Active profile: "
                + self.case.state.active_profile
                + ". "
                + profile_prompt(self.case.state.active_profile),
            },
        ]
        if summary:
            self.messages.append(
                {"role": "system", "content": "Persistent summary from prior work:\n" + summary}
            )

    def respond(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        self.sessions.record("message", role="user", content=text)
        tools = self.registry.schemas(self.case.state.active_profile)
        for _ in range(self.config.limits.max_tool_rounds):
            assistant = self.client.complete(self.messages, tools)
            history = assistant.as_history_message()
            self.messages.append(history)
            self.sessions.record("message", role="assistant", content=history)
            if not assistant.tool_calls:
                if not assistant.content:
                    return "The model returned an empty response. Run maldroid doctor --model-tool-test."
                return assistant.content
            for call in assistant.tool_calls:
                self.sessions.record(
                    "tool_call",
                    role="assistant",
                    content={"id": call.id, "name": call.name, "arguments": call.arguments},
                )
                result = self.dispatcher.execute(call.name, call.arguments)
                serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
                tool_message = {"role": "tool", "tool_call_id": call.id, "content": serialized}
                self.messages.append(tool_message)
                self.sessions.record("tool_result", role="tool", content=tool_message)
        return "The tool-call round limit was reached. Refine the request or inspect saved tool output."

    def switch_profile(self, profile: str) -> None:
        self.case.state.active_profile = profile
        self.messages.append(
            {
                "role": "system",
                "content": "Profile changed to " + profile + ". " + profile_prompt(profile),
            }
        )
        self.sessions.record("profile_change", content={"profile": profile})

    def estimate_tokens(self) -> int:
        serialized = json.dumps(self.messages, ensure_ascii=False)
        return max(1, len(serialized) // 4)

    def compact(self) -> str:
        prompt = {
            "role": "user",
            "content": (
                "Create a concise structured session summary. Preserve confirmed findings, hypotheses, "
                "open TODO items, important evidence paths and line ranges, active profile, and uncertainty."
            ),
        }
        summary_message = self.client.complete(self.messages + [prompt], [])
        summary = (
            summary_message.content or self.case.state.summary or "No session summary was produced."
        )
        self.sessions.record("compaction", content={"summary": summary})
        self.sessions.save_summary(summary)
        self._reset_messages(summary)
        return summary

    def clear(self) -> None:
        self.sessions.record("clear", content={})
        self._reset_messages(self.case.state.summary)
