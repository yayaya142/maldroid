from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.exceptions import ConfigurationError
from maldroid.external_mcp import (
    ExternalMcpRegistryManager,
    ExternalMcpRuntime,
    concise_mcp_error,
    external_tool_alias,
)
from maldroid.investigation import InvestigationManager
from maldroid.llama_client import AssistantMessage, ToolCall
from maldroid.mcp_server import MalDroidMcpServer
from maldroid.paths import PathPolicy
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_external_mcp_registry_persists_servers_and_history(tmp_path: Path) -> None:
    manager = ExternalMcpRegistryManager(tmp_path / "config")
    server = manager.add("http://127.0.0.1:9123/mcp", "ghidra")

    assert server.transport == "streamable-http"
    assert manager.load().servers == [server]
    assert manager.history()[-1]["action"] == "add"

    removed = manager.remove("GHIDRA")
    assert removed.nickname == "ghidra"
    assert manager.load().servers == []
    assert manager.history()[-1]["action"] == "remove"


def test_external_mcp_registry_supports_sse_and_rejects_remote_hosts(tmp_path: Path) -> None:
    manager = ExternalMcpRegistryManager(tmp_path / "config")

    server = manager.add("http://localhost:8080/sse")

    assert server.nickname == "local-8080"
    assert server.transport == "sse"
    with pytest.raises(ConfigurationError, match="localhost"):
        manager.add("https://example.com/mcp", "remote")
    with pytest.raises(ConfigurationError, match="query"):
        manager.add("http://127.0.0.1:8080/mcp?token=secret", "secret")
    assert (
        concise_mcp_error(ExceptionGroup("task group", [ConnectionError("refused")])) == "refused"
    )


class ExternalCallingClient:
    def __init__(self, alias: str) -> None:
        self.alias = alias
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="external", name=self.alias, arguments="{}")],
            )
        if self.calls == 2:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="checkpoint",
                        name=mcp_tool_name("save_note"),
                        arguments='{"text":"External MCP case state was inspected."}',
                    )
                ],
            )
        return AssistantMessage(content="done")


def test_external_mcp_runtime_discovers_namespaces_and_executes(
    app_config: AppConfig, tmp_path: Path
) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    registry = build_registry()
    dispatcher = ToolDispatcher(
        registry,
        ToolContext(
            config=app_config,
            case=case,
            case_manager=manager,
            investigation=InvestigationManager(manager),
            path_policy=PathPolicy(case.root),
        ),
    )
    server = MalDroidMcpServer(app_config, registry, dispatcher)
    endpoint = server.start(free_port())
    connector_manager = ExternalMcpRegistryManager(tmp_path / "external-config")
    connector_manager.add(endpoint, "fixture")
    runtime = ExternalMcpRuntime(app_config, case, connector_manager)
    try:
        statuses = runtime.refresh()
        alias = external_tool_alias("fixture", mcp_tool_name("read_case_state"))

        assert statuses[0]["status"] == "connected"
        assert runtime.handles(alias)
        assert any(item["function"]["name"] == alias for item in runtime.schemas())
        result = runtime.execute(alias, {})
        assert result.status == "completed"

        sessions = SessionManager(case, manager)
        agent = MalDroidAgent(
            app_config,
            case,
            ExternalCallingClient(alias),
            registry,
            dispatcher,
            sessions,
            external_mcp=runtime,
        )
        assert any(item["function"]["name"] == alias for item in agent.available_tool_schemas())
        assert agent.respond("Inspect external MCP state") == "done"
        events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
        assert any(
            event["type"] == "tool_call" and event["content"]["name"] == alias for event in events
        )
    finally:
        server.stop()
