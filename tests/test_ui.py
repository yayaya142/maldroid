from __future__ import annotations

from io import StringIO

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
    reasoning = list(completer.get_completions(Document("/reasoning hi"), CompleteEvent()))

    assert [item.text for item in commands] == ["/context"]
    assert [item.text for item in profiles] == ["react-native"]
    assert [item.text for item in reasoning] == ["high"]


def test_toolbar_exposes_remaining_context_and_durable_state(app_config) -> None:
    chat, _ = make_chat(app_config)
    chat.investigation.save_note(chat.case, "Continue with the manifest.")
    toolbar = "".join(fragment[1] for fragment in chat._bottom_toolbar())

    assert "ctx" in toolbar
    assert "left" in toolbar
    assert "generic" in toolbar
    assert "1 notes" in toolbar


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
