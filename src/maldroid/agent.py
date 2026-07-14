"""Bounded local-model conversation and tool-calling loop."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from maldroid.case_manager import Case
from maldroid.config import AppConfig
from maldroid.llama_client import REASONING_BUDGETS, AssistantMessage, ModelClient, ReasoningLevel
from maldroid.prompts import SYSTEM_PROMPT, profile_prompt
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolExecutor
from maldroid.tools.models import mcp_tool_name
from maldroid.tools.registry import ToolRegistry

CHECKPOINT_TOOLS = {
    mcp_tool_name("save_note"),
    mcp_tool_name("save_finding"),
    mcp_tool_name("update_finding"),
}
NON_INVESTIGATION_TOOLS = {
    mcp_tool_name("read_case_state"),
    mcp_tool_name("list_case_files"),
}
CHECKPOINT_REMINDER = (
    "A durable progress checkpoint is required before the final answer. Call "
    "MalDroid_save_note now. Record completed work, exact evidence paths and lines or offsets, "
    "facts versus hypotheses, uncertainty, unresolved questions, and the exact next action. "
    "Do not rely on conversation history alone."
)
CONTINUATION_INSTRUCTION = (
    "Continue the same user task autonomously from the durable checkpoint. Do not ask the user to "
    "repeat the objective and do not stop merely to report progress. Inspect the saved case state, "
    "continue using bounded tools, distinguish facts from hypotheses, and finish only when the "
    "requested investigation is complete or a genuine external dependency requires user action."
)

AgentEventHandler = Callable[[str, dict[str, Any]], None]


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
        event_handler: AgentEventHandler | None = None,
    ):
        self.config = config
        self.case = case
        self.client = client
        self.registry = registry
        self.dispatcher = dispatcher
        self.sessions = sessions
        self.event_handler = event_handler
        self.messages: list[dict[str, Any]] = []
        model_event_setter = getattr(self.client, "set_event_handler", None)
        if model_event_setter is not None:
            model_event_setter(self._handle_model_event)
        self._reset_messages(previous_summary)

    def _emit(self, event: str, **data: Any) -> None:
        if self.event_handler is not None:
            self.event_handler(event, data)

    def _handle_model_event(self, event: str, data: dict[str, Any]) -> None:
        self._emit(event, **data)

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
        phase = 1
        phase_tool_rounds = 0
        total_tool_rounds = 0
        investigation_performed = False
        checkpoint_saved = False
        checkpoint_requested = False
        activity: list[str] = []
        while True:
            self._emit(
                "model_start",
                phase=phase,
                phase_tool_round=phase_tool_rounds,
                total_tool_rounds=total_tool_rounds,
                input_tokens_estimate=self.estimate_tokens(),
            )
            assistant = self._complete_with_retries(self.messages, tools)
            history = assistant.as_history_message()
            self.messages.append(history)
            self.sessions.record("message", role="assistant", content=history)
            if not assistant.tool_calls:
                if not assistant.content:
                    return "The model returned an empty response. Run maldroid doctor --model-tool-test."
                if investigation_performed and not checkpoint_saved:
                    if not checkpoint_requested:
                        self._emit("checkpoint_required")
                        self.messages.append({"role": "system", "content": CHECKPOINT_REMINDER})
                        self.sessions.record("checkpoint_required", content={})
                        checkpoint_requested = True
                        continue
                    self._save_automatic_checkpoint(assistant.content, activity)
                return assistant.content
            phase_tool_rounds += 1
            total_tool_rounds += 1
            for call in assistant.tool_calls:
                self.sessions.record(
                    "tool_call",
                    role="assistant",
                    content={"id": call.id, "name": call.name, "arguments": call.arguments},
                )
                self._emit("tool_start", name=call.name, arguments=call.arguments)
                result = self.dispatcher.execute(call.name, call.arguments)
                self._emit(
                    "tool_result",
                    name=call.name,
                    status=result.status,
                    truncated=result.truncated,
                    output_file=result.output_file,
                    error=result.error.message if result.error else None,
                )
                activity.append(f"{call.name} ({result.status})")
                if call.name in CHECKPOINT_TOOLS:
                    if result.status == "completed" and investigation_performed:
                        checkpoint_saved = True
                elif call.name not in NON_INVESTIGATION_TOOLS:
                    investigation_performed = True
                serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
                tool_message = {"role": "tool", "tool_call_id": call.id, "content": serialized}
                self.messages.append(tool_message)
                self.sessions.record("tool_result", role="tool", content=tool_message)
            round_rollover = phase_tool_rounds >= self.config.limits.max_tool_rounds
            context_rollover = self.should_auto_compact()
            if round_rollover or context_rollover:
                self._save_phase_checkpoint(text, activity, phase, total_tool_rounds)
                rollover_reason = "context_threshold" if context_rollover else "tool_window"
                self._emit(
                    "phase_rollover",
                    completed_phase=phase,
                    total_tool_rounds=total_tool_rounds,
                    reason=rollover_reason,
                )
                self.compact()
                phase += 1
                phase_tool_rounds = 0
                investigation_performed = False
                checkpoint_saved = False
                checkpoint_requested = False
                activity = []
                self.messages.append(
                    {
                        "role": "system",
                        "content": CONTINUATION_INSTRUCTION
                        + "\n\nOriginal objective:\n"
                        + text[:12000],
                    }
                )

    def _complete_with_retries(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantMessage:
        attempts = self.config.limits.model_retry_attempts
        for attempt in range(1, attempts + 1):
            try:
                return self.client.complete(messages, tools)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                if attempt >= attempts:
                    raise
                delay = min(4.0, float(2 ** (attempt - 1)))
                self._emit(
                    "model_retry",
                    attempt=attempt,
                    max_attempts=attempts,
                    delay_seconds=delay,
                    error=str(exc),
                )
                self.sessions.record(
                    "model_retry",
                    content={"attempt": attempt, "delay_seconds": delay, "error": str(exc)},
                )
                time.sleep(delay)
        raise RuntimeError("Model retry loop exited unexpectedly")

    def _save_phase_checkpoint(
        self,
        objective: str,
        activity: list[str],
        phase: int,
        total_tool_rounds: int,
    ) -> None:
        tools = "\n".join(f"- {item}" for item in activity[-40:]) or "- none recorded"
        text = (
            f"Autonomous phase {phase} checkpoint after {total_tool_rounds} tool rounds.\n\n"
            f"Original objective:\n{objective[:8000]}\n\n"
            f"Recent tool activity:\n{tools}\n\n"
            "The agent is continuing automatically from this checkpoint. Consult findings, TODOs, "
            "tool outputs, and the session summary for detailed evidence and the exact next action."
        )
        result = self.dispatcher.execute(mcp_tool_name("save_note"), {"text": text[:40000]})
        self.sessions.record(
            "phase_checkpoint",
            content={
                "phase": phase,
                "total_tool_rounds": total_tool_rounds,
                "status": result.status,
                "error": result.error.model_dump() if result.error else None,
            },
        )
        self._emit(
            "phase_checkpoint",
            phase=phase,
            total_tool_rounds=total_tool_rounds,
            status=result.status,
        )

    def _save_automatic_checkpoint(self, draft: str, activity: list[str] | None = None) -> None:
        tool_summary = ""
        if activity:
            tool_summary = "\n\nTools executed:\n" + "\n".join(
                f"- {item}" for item in activity[-20:]
            )
        text = (
            "Automatic progress checkpoint because the model did not call MalDroid_save_note.\n\n"
            + draft
            + tool_summary
        )
        text = text[:40000]
        result = self.dispatcher.execute(mcp_tool_name("save_note"), {"text": text})
        self._emit("automatic_checkpoint", status=result.status)
        self.sessions.record(
            "automatic_checkpoint",
            content={
                "status": result.status,
                "error": result.error.model_dump() if result.error else None,
            },
        )

    def switch_profile(self, profile: str) -> None:
        self.case.state.active_profile = profile
        self.messages.append(
            {
                "role": "system",
                "content": "Profile changed to " + profile + ". " + profile_prompt(profile),
            }
        )
        self.sessions.record("profile_change", content={"profile": profile})

    @property
    def reasoning_level(self) -> ReasoningLevel:
        value = getattr(self.client, "reasoning_level", self.config.llama.reasoning_level)
        return value if value in REASONING_BUDGETS else self.config.llama.reasoning_level

    def set_reasoning_level(self, level: ReasoningLevel) -> None:
        setter = getattr(self.client, "set_reasoning_level", None)
        if setter is None:
            raise RuntimeError("The active model client does not support reasoning controls")
        setter(level)
        self.sessions.record(
            "reasoning_change",
            content={"level": level, "thinking_budget_tokens": REASONING_BUDGETS[level]},
        )

    def estimate_tokens(self) -> int:
        serialized = json.dumps(
            {
                "messages": self.messages,
                "tools": self.registry.schemas(self.case.state.active_profile),
            },
            ensure_ascii=False,
        )
        return max(1, len(serialized) // 4)

    def context_ratio(self) -> float:
        return self.estimate_tokens() / self.case.state.context_size

    def should_auto_compact(self) -> bool:
        return self.context_ratio() >= self.config.limits.auto_compact_ratio

    def compact(self) -> str:
        self._emit("compaction_start")
        prompt = {
            "role": "user",
            "content": (
                "Create a concise structured session summary. Preserve completed work, confirmed "
                "findings, hypotheses, open TODO items, important evidence paths and line ranges, "
                "failed approaches, active profile, uncertainty, and the exact next action."
            ),
        }
        try:
            summary_message = self.client.complete(self.messages + [prompt], [])
            summary = summary_message.content or self._durable_fallback_summary()
        except Exception as exc:
            summary = self._durable_fallback_summary(f"Model compaction failed: {exc}")
        self.sessions.record("compaction", content={"summary": summary})
        self.sessions.save_summary(summary)
        self._reset_messages(summary)
        self._emit("compaction_complete", summary_length=len(summary))
        return summary

    def _durable_fallback_summary(self, warning: str = "") -> str:
        sections = [f"Active profile: {self.case.state.active_profile}"]
        if warning:
            sections.append(warning)
        if self.case.state.findings:
            sections.append(
                "Findings:\n"
                + "\n".join(
                    f"- {item.id} [{item.status}/{item.confidence}]: {item.title} — {item.summary}"
                    for item in self.case.state.findings[-20:]
                )
            )
        if self.case.state.notes:
            sections.append(
                "Recent progress notes:\n"
                + "\n".join(f"- {item.id}: {item.text}" for item in self.case.state.notes[-20:])
            )
        open_todos = [item for item in self.case.state.todos if item.status == "open"]
        if open_todos:
            sections.append(
                "Open TODOs:\n" + "\n".join(f"- {item.id}: {item.text}" for item in open_todos)
            )
        if self.case.state.summary:
            sections.append("Previous summary:\n" + self.case.state.summary)
        if len(sections) == 1:
            sections.append("No durable investigation progress has been recorded yet.")
        return "\n\n".join(sections)[:40000]

    def clear(self) -> None:
        self.sessions.record("clear", content={})
        self._reset_messages(self.case.state.summary)
