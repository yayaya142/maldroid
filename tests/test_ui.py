from __future__ import annotations

import time
from io import StringIO
from unittest.mock import Mock

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import CaseManager
from maldroid.investigation import InvestigationManager
from maldroid.paths import PathPolicy
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import build_registry
from maldroid.ui import InteractiveChat, MalDroidCompleter


class NeverCalledClient:
    @staticmethod
    def complete(messages, tools):
        raise AssertionError("The UI unit test must not call the model")


class FakeServer:
    @staticmethod
    def status():
        return {"running": True, "port": 7575, "pid": 1234}


def make_chat(app_config):
    manager = CaseManager(app_config)
    case = manager.create("terminal-test")
    investigation = InvestigationManager(manager)
    registry = build_registry()
    dispatcher = ToolDispatcher(
        registry,
        ToolContext(
            config=app_config,
            case=case,
            case_manager=manager,
            investigation=investigation,
            path_policy=PathPolicy(case.root),
        ),
    )
    agent = MalDroidAgent(
        app_config,
        case,
        NeverCalledClient(),
        registry,
        dispatcher,
        SessionManager(case, manager),
    )
    output = StringIO()
    chat = InteractiveChat(
        Console(file=output, force_terminal=False),
        case,
        manager,
        investigation,
        FakeServer(),
        agent,
        registry,
        dispatcher,
        "http://127.0.0.1:8765/mcp",
    )
    return chat, output


def test_slash_completion_includes_commands_and_profiles() -> None:
    completer = MalDroidCompleter()
    commands = list(completer.get_completions(Document("/cont"), CompleteEvent()))
    profiles = list(completer.get_completions(Document("/profile rea"), CompleteEvent()))
    automatic = list(completer.get_completions(Document("/profile au"), CompleteEvent()))
    reasoning = list(completer.get_completions(Document("/reasoning hi"), CompleteEvent()))

    assert [item.text for item in commands] == ["/context"]
    assert [item.text for item in profiles] == ["react-native"]
    assert [item.text for item in automatic] == ["auto"]
    assert [item.text for item in reasoning] == ["high"]


def test_toolbar_exposes_remaining_context_and_durable_state(app_config) -> None:
    chat, _ = make_chat(app_config)
    chat.investigation.save_checkpoint(
        chat.case,
        objective="Inspect the manifest",
        completed_work=["Mapped exported components"],
        next_action="Trace component entrypoints",
    )
    toolbar = "".join(fragment[1] for fragment in chat._bottom_toolbar())

    assert "ctx" in toolbar
    assert "left" in toolbar
    assert "generic" in toolbar
    assert "1 checkpoints" in toolbar


def test_dashboard_and_direct_report_commands_are_research_focused(app_config) -> None:
    chat, output = make_chat(app_config)
    chat.investigation.save_checkpoint(
        chat.case,
        objective="Trace network behavior",
        completed_work=["Located the request builder"],
        next_action="Trace callers",
    )

    assert chat._slash("/dashboard") is True
    assert chat._slash("/report") is True

    rendered = output.getvalue()
    assert "Research dashboard" in rendered
    assert "Trace callers" in rendered
    assert "reports/RESEARCH_REPORT.md" in rendered


def test_live_tool_event_is_human_readable(app_config) -> None:
    chat, output = make_chat(app_config)
    chat._handle_agent_event(
        "tool_start",
        {"name": "MalDroid_read_file_range", "arguments": {"path": "sample.txt"}},
    )
    chat._handle_agent_event(
        "tool_result",
        {"name": "MalDroid_read_file_range", "status": "completed", "truncated": False},
    )

    rendered = output.getvalue()
    assert "read_file_range" in rendered
    assert "sample.txt" in rendered
    assert "completed" not in rendered


def test_live_generation_status_shows_token_consumption(app_config) -> None:
    chat, _ = make_chat(app_config)
    status = Mock()
    chat._status = status
    chat._turn_started = time.monotonic()

    chat._handle_agent_event(
        "generation_progress",
        {
            "completion_tokens_estimate": 25,
            "content_characters": 20,
            "reasoning_characters": 80,
        },
    )

    rendered = status.update.call_args.args[0]
    assert "Reasoning" in rendered
    assert "out ≈25 tok" in rendered
    assert "ctx ≈" in rendered
    assert "left" in rendered


def test_state_discipline_event_is_visible(app_config) -> None:
    chat, output = make_chat(app_config)

    chat._handle_agent_event("state_discipline_required", {})

    rendered = output.getvalue()
    assert "TODO/Finding state" in rendered
