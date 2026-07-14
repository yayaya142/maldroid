from __future__ import annotations

import socket

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.exceptions import McpServerError
from maldroid.investigation import InvestigationManager
from maldroid.llama_client import AssistantMessage, ToolCall
from maldroid.mcp_server import MalDroidMcpServer, McpToolClient
from maldroid.paths import PathPolicy
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import build_registry


def make_server(config: AppConfig) -> tuple[MalDroidMcpServer, ToolDispatcher]:
    manager = CaseManager(config)
    case = manager.create()
    registry = build_registry()
    dispatcher = ToolDispatcher(
        registry,
        ToolContext(
            config=config,
            case=case,
            case_manager=manager,
            investigation=InvestigationManager(manager),
            path_policy=PathPolicy(case.root),
        ),
    )
    return MalDroidMcpServer(config, registry, dispatcher), dispatcher


async def list_tool_names(endpoint: str) -> set[str]:
    async with (
        streamable_http_client(endpoint) as (read, write, _session_id),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return {tool.name for tool in result.tools}


def test_mcp_lists_profile_tools_and_executes_through_http(app_config: AppConfig) -> None:
    server, dispatcher = make_server(app_config)
    endpoint = server.start()
    try:
        names = anyio.run(list_tool_names, endpoint)
        assert "read_case_state" in names
        assert "inspect_javascript_bundle" not in names

        client = McpToolClient(endpoint)
        result = client.execute("read_case_state", {})
        assert result.status == "completed"
        assert result.data["active_profile"] == "generic"

        dispatcher.context.case.state.active_profile = "react-native"
        names = anyio.run(list_tool_names, endpoint)
        assert "inspect_javascript_bundle" in names
    finally:
        server.stop()


def test_mcp_explicit_busy_port_fails_and_default_falls_back(app_config: AppConfig) -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    busy_port = int(occupied.getsockname()[1])
    data = app_config.model_dump()
    data["mcp"]["preferred_port"] = busy_port
    config = AppConfig.model_validate(data)
    server, _ = make_server(config)
    try:
        try:
            server.start(busy_port, explicit_port=True)
        except McpServerError as exc:
            assert "explicitly requested MCP port" in str(exc)
        else:  # pragma: no cover - protects the port contract
            raise AssertionError("An explicit busy MCP port must fail")

        endpoint = server.start()
        assert server.port != busy_port
        assert endpoint.endswith("/mcp")
    finally:
        server.stop()
        occupied.close()


def test_agent_tool_round_trip_uses_mcp_client(app_config: AppConfig) -> None:
    server, dispatcher = make_server(app_config)
    endpoint = server.start()

    class FakeModel:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AssistantMessage(
                    content=None,
                    tool_calls=[ToolCall(id="mcp-call", name="read_case_state", arguments="{}")],
                )
            assert any(message.get("role") == "tool" for message in messages)
            return AssistantMessage(content="MCP tool completed.")

    try:
        case = dispatcher.context.case
        sessions = SessionManager(case, dispatcher.context.case_manager)
        model = FakeModel()
        agent = MalDroidAgent(
            app_config,
            case,
            model,
            server.registry,
            McpToolClient(endpoint),
            sessions,
        )
        assert agent.respond("Read state") == "MCP tool completed."
        assert model.calls == 2
    finally:
        server.stop()
