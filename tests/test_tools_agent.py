from __future__ import annotations

import json
from pathlib import Path

from maldroid.agent import CHECKPOINT_REMINDER, MalDroidAgent
from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.knowledge_manager import KnowledgeManager
from maldroid.llama_client import AssistantMessage, ToolCall
from maldroid.paths import PathPolicy
from maldroid.prompts import SYSTEM_PROMPT
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import MCP_TOOL_PREFIX, ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def make_dispatcher(app_config: AppConfig):
    manager = CaseManager(app_config)
    case = manager.create()
    investigation = InvestigationManager(manager)
    registry = build_registry()
    context = ToolContext(
        config=app_config,
        case=case,
        case_manager=manager,
        investigation=investigation,
        path_policy=PathPolicy(case.root),
    )
    return manager, case, registry, ToolDispatcher(registry, context)


def test_documented_system_prompt_matches_runtime_prompt() -> None:
    document = (Path(__file__).resolve().parents[1] / "SYSTEM_PROMPT.md").read_text(
        encoding="utf-8"
    )
    assert SYSTEM_PROMPT.strip() in document
    assert "MalDroid_read_case_state, then MalDroid_list_case_files" in SYSTEM_PROMPT


def test_registry_profile_filtering(app_config: AppConfig) -> None:
    _, _, registry, _ = make_dispatcher(app_config)
    generic = set(registry.names("generic"))
    react_native = set(registry.names("react-native"))
    assert mcp_tool_name("read_file_range") in generic
    assert mcp_tool_name("inspect_javascript_bundle") not in generic
    assert generic < react_native
    assert all(name.startswith(MCP_TOOL_PREFIX) for name in react_native)
    assert not any("flutter" in name or "unity" in name for name in generic)


def test_dispatcher_executes_and_rejects_profile_tool(app_config: AppConfig) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    sample = case.root / "sample.txt"
    sample.write_text("one\nneedle\nthree\n", encoding="utf-8")
    result = dispatcher.execute(
        mcp_tool_name("read_file_range"),
        {"path": "sample.txt", "start_line": 2, "end_line": 2},
    )
    assert result.status == "completed"
    assert result.data["lines"][0]["text"] == "needle"
    disabled = dispatcher.execute(
        mcp_tool_name("inspect_javascript_bundle"), {"path": "sample.txt"}
    )
    assert disabled.error and disabled.error.code == "disabled_tool"
    invalid = dispatcher.execute(mcp_tool_name("read_file_range"), "not-json")
    assert invalid.error and invalid.error.code == "invalid_json"
    unprefixed = dispatcher.execute("read_file_range", {})
    assert unprefixed.error and unprefixed.error.code == "unknown_tool"


def test_dispatcher_saves_oversized_output(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["limits"]["max_tool_output_characters"] = 1000
    limited = AppConfig.model_validate(data)
    _, case, _, dispatcher = make_dispatcher(limited)
    sample = case.root / "large-line.txt"
    sample.write_text("x" * 5000 + "\n", encoding="utf-8")
    result = dispatcher.execute(
        mcp_tool_name("read_file_range"),
        {"path": sample.name, "start_line": 1, "end_line": 1},
    )
    assert result.truncated is True
    assert result.output_file
    assert (case.root / result.output_file).is_file()


def test_builtin_knowledge_reindex_search_and_bounded_read(app_config: AppConfig) -> None:
    manager, case, _, _ = make_dispatcher(app_config)
    knowledge = KnowledgeManager(case)
    indexed = knowledge.reindex()
    assert indexed["documents"] >= 10
    matches = knowledge.search("Metro bundle", "react-native")
    assert matches
    excerpt = knowledge.read_range(matches[0]["document_key"], 1, 8)
    assert excerpt["lines"]


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    def complete(self, messages, tools):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                reasoning_content="bounded reasoning",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name=mcp_tool_name("read_case_state"),
                        arguments="{}",
                    )
                ],
            )
        return AssistantMessage(content="Investigation state inspected.")


def test_agent_tool_call_round_trip(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    client = FakeClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)
    response = agent.respond("Inspect current state")
    assert response == "Investigation state inspected."
    assert client.calls == 2
    assert any(message.get("role") == "tool" for message in client.messages)
    assistant = next(message for message in client.messages if message.get("role") == "assistant")
    assert assistant["reasoning_content"] == "bounded reasoning"
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    assert {event["type"] for event in events} >= {"tool_call", "tool_result"}


def test_agent_reports_live_model_and_tool_events(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    reported: list[tuple[str, dict]] = []
    agent = MalDroidAgent(
        app_config,
        case,
        FakeClient(),
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, data: reported.append((event, data)),
    )

    agent.respond("Inspect current state")

    assert [event for event, _ in reported].count("model_start") == 2
    assert any(event == "tool_start" for event, _ in reported)
    result = next(data for event, data in reported if event == "tool_result")
    assert result["name"] == "MalDroid_read_case_state"
    assert result["status"] == "completed"


class CheckpointingClient:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    def complete(self, messages, tools):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="inspect-1",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )
        if self.calls == 2:
            return AssistantMessage(content="The sample is a small text artifact.")
        if self.calls == 3:
            assert any(message.get("content") == CHECKPOINT_REMINDER for message in messages)
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="note-1",
                        name=mcp_tool_name("save_note"),
                        arguments=(
                            '{"text":"Inspected sample.txt metadata. Next: read relevant lines."}'
                        ),
                    )
                ],
            )
        return AssistantMessage(content="Checkpoint saved; inspect relevant lines next.")


def test_agent_requires_durable_checkpoint_after_investigation(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    sessions = SessionManager(case, manager)
    client = CheckpointingClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)

    response = agent.respond("Inspect the sample")

    assert response == "Checkpoint saved; inspect relevant lines next."
    assert client.calls == 4
    assert case.state.notes[-1].text.startswith("Inspected sample.txt metadata")
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    assert "checkpoint_required" in {event["type"] for event in events}


class CheckpointIgnoringClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="inspect-1",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )
        return AssistantMessage(content="Metadata inspected; read the suspicious range next.")


def test_agent_saves_automatic_checkpoint_when_model_ignores_reminder(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(
        app_config,
        case,
        CheckpointIgnoringClient(),
        registry,
        dispatcher,
        sessions,
    )

    response = agent.respond("Inspect the sample")

    assert response == "Metadata inspected; read the suspicious range next."
    assert case.state.notes[-1].text.startswith("Automatic progress checkpoint")
    assert "read the suspicious range next" in case.state.notes[-1].text
    assert "MalDroid_get_file_info (completed)" in case.state.notes[-1].text


class FailingCompactionClient:
    @staticmethod
    def complete(messages, tools):
        raise RuntimeError("context exhausted")


def test_compaction_falls_back_to_durable_case_state(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    dispatcher.execute(mcp_tool_name("save_note"), {"text": "Resume at sample.txt line 42."})
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(
        app_config,
        case,
        FailingCompactionClient(),
        registry,
        dispatcher,
        sessions,
    )

    summary = agent.compact()

    assert "Model compaction failed" in summary
    assert "Resume at sample.txt line 42" in summary
    assert case.state.summary == summary


def test_auto_compaction_threshold_is_configurable(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(app_config, case, FakeClient(), registry, dispatcher, sessions)
    agent.messages.append({"role": "user", "content": "x" * 190000})
    assert agent.should_auto_compact() is True
