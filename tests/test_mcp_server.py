from __future__ import annotations

import socket

import anyio
import httpx
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
from maldroid.tools.models import MCP_TOOL_PREFIX, ToolContext, mcp_tool_name
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


async def list_tool_names_from_browser(endpoint: str, origin: str) -> set[str]:
    async with (
        httpx.AsyncClient(headers={"Origin": origin}) as http_client,
        streamable_http_client(endpoint, http_client=http_client) as (
            read,
            write,
            _session_id,
        ),
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
        assert mcp_tool_name("read_case_state") in names
        assert mcp_tool_name("inspect_javascript_bundle") not in names
        assert all(name.startswith(MCP_TOOL_PREFIX) for name in names)

        client = McpToolClient(endpoint)
        result = client.execute(mcp_tool_name("read_case_state"), {})
        assert result.status == "completed"
        assert result.data["active_profile"] == "generic"

        dispatcher.context.case.state.active_profile = "react-native"
        names = anyio.run(list_tool_names, endpoint)
        assert mcp_tool_name("inspect_javascript_bundle") in names
    finally:
        server.stop()


def test_mcp_registers_case_local_evidence_and_preserves_error_payload(
    app_config: AppConfig,
) -> None:
    server, dispatcher = make_server(app_config)
    source = dispatcher.context.case.root / "index.android.bundle"
    source.write_text("console.log('fixture');\n", encoding="utf-8")
    endpoint = server.start()
    try:
        client = McpToolClient(endpoint)
        registered = client.execute(
            mcp_tool_name("register_evidence"),
            {"path": source.name, "mode": "copy", "calculate_hash": True},
        )
        assert registered.status == "completed"
        assert registered.data["case_path"].startswith("evidence/")

        invalid = client.execute(
            mcp_tool_name("register_evidence"),
            {"path": "missing.bundle", "mode": "copy"},
        )
        assert invalid.status == "error"
        assert invalid.error and invalid.error.code != "invalid_mcp_result"
    finally:
        server.stop()


def test_mcp_accepts_llama_webui_origin_and_cors_preflight(app_config: AppConfig) -> None:
    server, _dispatcher = make_server(app_config)
    endpoint = server.start()
    origin = f"http://127.0.0.1:{app_config.llama.preferred_port}"
    try:
        names = anyio.run(list_tool_names_from_browser, endpoint, origin)
        assert mcp_tool_name("read_case_state") in names

        response = httpx.options(
            endpoint,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,mcp-protocol-version",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    finally:
        server.stop()


def test_mcp_rejects_non_llama_browser_origin(app_config: AppConfig) -> None:
    server, _dispatcher = make_server(app_config)
    endpoint = server.start()
    try:
        response = httpx.post(
            endpoint,
            headers={
                "Origin": "https://untrusted.example",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "untrusted", "version": "1"},
                },
            },
        )
        assert response.status_code == 403
    finally:
        server.stop()


def test_mcp_fixed_busy_port_fails_without_fallback(app_config: AppConfig) -> None:
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
            server.start()
        except McpServerError as exc:
            assert f"fixed MCP port {busy_port}" in str(exc)
            assert "config set mcp.preferred_port" in str(exc)
        else:  # pragma: no cover - protects the fixed-port contract
            raise AssertionError("A busy configured MCP port must fail without fallback")
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
                    tool_calls=[
                        ToolCall(
                            id="mcp-call",
                            name=mcp_tool_name("read_case_state"),
                            arguments="{}",
                        )
                    ],
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
