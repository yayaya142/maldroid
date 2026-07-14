from __future__ import annotations

import json

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.knowledge_manager import KnowledgeManager
from maldroid.llama_client import AssistantMessage, ToolCall
from maldroid.paths import PathPolicy
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
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


def test_registry_profile_filtering(app_config: AppConfig) -> None:
    _, _, registry, _ = make_dispatcher(app_config)
    generic = set(registry.names("generic"))
    react_native = set(registry.names("react-native"))
    assert "read_file_range" in generic
    assert "inspect_javascript_bundle" not in generic
    assert generic < react_native
    assert not any("flutter" in name or "unity" in name for name in generic)


def test_dispatcher_executes_and_rejects_profile_tool(app_config: AppConfig) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    sample = case.root / "sample.txt"
    sample.write_text("one\nneedle\nthree\n", encoding="utf-8")
    result = dispatcher.execute(
        "read_file_range", {"path": "sample.txt", "start_line": 2, "end_line": 2}
    )
    assert result.status == "completed"
    assert result.data["lines"][0]["text"] == "needle"
    disabled = dispatcher.execute("inspect_javascript_bundle", {"path": "sample.txt"})
    assert disabled.error and disabled.error.code == "disabled_tool"
    invalid = dispatcher.execute("read_file_range", "not-json")
    assert invalid.error and invalid.error.code == "invalid_json"


def test_dispatcher_saves_oversized_output(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["limits"]["max_tool_output_characters"] = 1000
    limited = AppConfig.model_validate(data)
    _, case, _, dispatcher = make_dispatcher(limited)
    sample = case.root / "large-line.txt"
    sample.write_text("x" * 5000 + "\n", encoding="utf-8")
    result = dispatcher.execute(
        "read_file_range", {"path": sample.name, "start_line": 1, "end_line": 1}
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
                        name="read_case_state",
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
