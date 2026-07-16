"""Persistent loopback MCP connectors and namespaced external tool execution."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import anyio
from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field

from maldroid.case_manager import Case
from maldroid.config import AppConfig
from maldroid.exceptions import ConfigurationError
from maldroid.io_utils import append_jsonl, atomic_write_json
from maldroid.models import ToolError, ToolResult, now_iso
from maldroid.paths import config_directory

NICKNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
TOOL_CHARACTER_PATTERN = re.compile(r"[^A-Za-z0-9_-]")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ExternalMcpServer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nickname: str
    url: str
    transport: Literal["streamable-http", "sse"]
    added_at: str = Field(default_factory=now_iso)


class ExternalMcpRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    servers: list[ExternalMcpServer] = Field(default_factory=list)


class ExternalMcpRegistryManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or config_directory()
        self.path = self.root / "mcp-servers.json"
        self.history_path = self.root / "mcp-servers-history.jsonl"

    def load(self) -> ExternalMcpRegistry:
        if not self.path.exists():
            return ExternalMcpRegistry()
        try:
            return ExternalMcpRegistry.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigurationError(
                f"Invalid external MCP registry in {self.path}: {exc}"
            ) from exc

    def add(self, url: str, nickname: str | None = None) -> ExternalMcpServer:
        normalized_url, transport = validate_external_mcp_url(url)
        selected_name = nickname or default_nickname(normalized_url)
        validate_nickname(selected_name)
        registry = self.load()
        if any(item.nickname.lower() == selected_name.lower() for item in registry.servers):
            raise ConfigurationError(f"An MCP server named '{selected_name}' already exists.")
        if any(item.url == normalized_url for item in registry.servers):
            raise ConfigurationError("That MCP URL is already saved.")
        server = ExternalMcpServer(
            nickname=selected_name,
            url=normalized_url,
            transport=transport,
        )
        registry.servers.append(server)
        self._save(registry)
        self.record("add", server=server.model_dump())
        return server

    def remove(self, nickname: str) -> ExternalMcpServer:
        registry = self.load()
        server = next(
            (item for item in registry.servers if item.nickname.lower() == nickname.lower()), None
        )
        if server is None:
            raise ConfigurationError(f"Unknown MCP server: {nickname}")
        registry.servers.remove(server)
        self._save(registry)
        self.record("remove", server=server.model_dump())
        return server

    def get(self, nickname: str) -> ExternalMcpServer:
        server = next(
            (item for item in self.load().servers if item.nickname.lower() == nickname.lower()),
            None,
        )
        if server is None:
            raise ConfigurationError(f"Unknown MCP server: {nickname}")
        return server

    def record(self, action: str, **details: Any) -> None:
        append_jsonl(self.history_path, {"timestamp": now_iso(), "action": action, **details})
        self.history_path.chmod(0o600)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        entries: deque[dict[str, Any]] = deque(maxlen=max(1, limit))
        with self.history_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(entries)

    def _save(self, registry: ExternalMcpRegistry) -> None:
        atomic_write_json(self.path, registry.model_dump(mode="json"))


class ExternalMcpClient:
    def __init__(self, server: ExternalMcpServer, timeout_seconds: int = 120) -> None:
        self.server = server
        self.timeout_seconds = timeout_seconds

    def list_tools(self) -> list[types.Tool]:
        return anyio.run(self._list_tools_async)

    def execute(self, name: str, raw_arguments: str | dict[str, Any]) -> ToolResult:
        try:
            arguments = (
                json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            )
        except json.JSONDecodeError as exc:
            return ToolResult(
                status="error",
                error=ToolError(code="invalid_json", message=f"Invalid tool arguments: {exc}"),
            )
        try:
            return anyio.run(self._execute_async, name, arguments)
        except Exception as exc:
            return ToolResult(
                status="error",
                error=ToolError(
                    code="external_mcp_transport_error", message=concise_mcp_error(exc)
                ),
            )

    async def _list_tools_async(self) -> list[types.Tool]:
        with anyio.fail_after(self.timeout_seconds):
            async with self._session() as session:
                response = await session.list_tools()
                return response.tools

    async def _execute_async(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        with anyio.fail_after(self.timeout_seconds):
            async with self._session() as session:
                response = await session.call_tool(
                    name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                )
        text = "\n".join(
            block.text for block in response.content if isinstance(block, types.TextContent)
        )
        if response.isError:
            return ToolResult(
                status="error",
                error=ToolError(
                    code="external_mcp_tool_error",
                    message=(text or "External MCP tool returned an error.")[:8000],
                ),
            )
        data: Any
        if response.structuredContent is not None:
            data = response.structuredContent
            if text:
                data = {"structured_content": data, "text": text}
        else:
            data = {
                "content": [block.model_dump(mode="json") for block in response.content],
            }
        return ToolResult(status="completed", data=data)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        if self.server.transport == "sse":
            async with (
                sse_client(
                    self.server.url,
                    timeout=float(self.timeout_seconds),
                    sse_read_timeout=float(self.timeout_seconds),
                ) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                yield session
            return
        async with (
            streamable_http_client(self.server.url) as (read, write, _session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session


class ExternalMcpRuntime:
    def __init__(self, config: AppConfig, case: Case, manager: ExternalMcpRegistryManager) -> None:
        self.config = config
        self.case = case
        self.manager = manager
        self.routes: dict[str, tuple[ExternalMcpServer, str]] = {}
        self.tool_schemas: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []

    def refresh(self) -> list[dict[str, Any]]:
        self.routes = {}
        self.tool_schemas = []
        self.statuses = []
        servers = self.manager.load().servers
        if not servers:
            return self.statuses

        def discover(server: ExternalMcpServer) -> tuple[list[types.Tool] | None, str | None]:
            try:
                tools = ExternalMcpClient(
                    server, self.config.mcp.startup_timeout_seconds
                ).list_tools()
                return tools, None
            except Exception as exc:
                return None, concise_mcp_error(exc)

        with ThreadPoolExecutor(max_workers=min(8, len(servers))) as executor:
            discoveries = list(executor.map(discover, servers))

        for server, (tools, error) in zip(servers, discoveries, strict=True):
            if tools is not None:
                server_routes: dict[str, tuple[ExternalMcpServer, str]] = {}
                server_schemas: list[dict[str, Any]] = []
                try:
                    for tool in tools:
                        alias = external_tool_alias(server.nickname, tool.name)
                        if alias in self.routes or alias in server_routes:
                            raise ConfigurationError(f"External MCP tool alias collision: {alias}")
                        server_routes[alias] = (server, tool.name)
                        server_schemas.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": alias,
                                    "description": (
                                        f"External MCP '{server.nickname}' (untrusted metadata): "
                                        + (tool.description or tool.name)[:800]
                                    ),
                                    "parameters": tool.inputSchema,
                                },
                            }
                        )
                except Exception as exc:
                    tools = None
                    error = concise_mcp_error(exc)
                else:
                    self.routes.update(server_routes)
                    self.tool_schemas.extend(server_schemas)
                    status = {
                        "nickname": server.nickname,
                        "url": server.url,
                        "status": "connected",
                        "tools": len(tools),
                    }
            if tools is None:
                status = {
                    "nickname": server.nickname,
                    "url": server.url,
                    "status": "unavailable",
                    "error": error or "Unknown MCP discovery error",
                    "tools": 0,
                }
            self.statuses.append(status)
            self.manager.record("connect", **status)
        return self.statuses

    def schemas(self) -> list[dict[str, Any]]:
        return list(self.tool_schemas)

    def handles(self, name: str) -> bool:
        return name in self.routes

    def execute(self, name: str, raw_arguments: str | dict[str, Any]) -> ToolResult:
        route = self.routes.get(name)
        if route is None:
            return ToolResult(
                status="error",
                error=ToolError(code="unknown_external_mcp_tool", message=f"Unknown tool: {name}"),
            )
        server, original_name = route
        result = ExternalMcpClient(server, self.config.limits.command_timeout_seconds).execute(
            original_name, raw_arguments
        )
        result = self._limit_output(name, result)
        append_jsonl(
            self.case.internal / "logs" / "tools.jsonl",
            {
                "started_at": now_iso(),
                "completed_at": now_iso(),
                "tool": name,
                "external_mcp": server.nickname,
                "status": result.status,
                "error_code": result.error.code if result.error else None,
                "truncated": result.truncated,
                "output_file": result.output_file,
            },
        )
        return result

    def _limit_output(self, name: str, result: ToolResult) -> ToolResult:
        if result.status == "error":
            return result
        serialized = json.dumps(result.data, ensure_ascii=False, default=str)
        limit = self.config.limits.max_tool_output_characters
        if len(serialized) <= limit:
            return result
        digest = hashlib.sha256((name + now_iso()).encode()).hexdigest()[:10]
        target = self.case.internal / "tool-output" / f"external-mcp-{digest}.json"
        atomic_write_json(target, result.data)
        return ToolResult(
            status="completed",
            data={"preview": serialized[:limit], "total_characters": len(serialized)},
            truncated=True,
            output_file=target.relative_to(self.case.root).as_posix(),
        )


def validate_external_mcp_url(url: str) -> tuple[str, Literal["streamable-http", "sse"]]:
    normalized = url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError("MCP URL must be a complete http:// or https:// URL.")
    if parsed.hostname.lower() not in LOOPBACK_HOSTS:
        raise ConfigurationError("External MCP servers must use localhost, 127.0.0.1, or ::1.")
    if parsed.username or parsed.password:
        raise ConfigurationError("Credentials must not be embedded in an MCP URL.")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("MCP URLs must not contain query parameters or fragments.")
    transport: Literal["streamable-http", "sse"] = (
        "sse" if parsed.path.lower().endswith("/sse") else "streamable-http"
    )
    return normalized, transport


def validate_nickname(nickname: str) -> None:
    if not NICKNAME_PATTERN.fullmatch(nickname):
        raise ConfigurationError(
            "MCP nickname must start with a letter and use at most 32 letters, numbers, _ or -."
        )


def default_nickname(url: str) -> str:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"local-{port}"


def external_tool_alias(nickname: str, tool_name: str) -> str:
    clean_name = TOOL_CHARACTER_PATTERN.sub("_", tool_name)
    candidate = f"MCP_{nickname}_{clean_name}"
    if len(candidate) <= 64:
        return candidate
    digest = hashlib.sha256(candidate.encode()).hexdigest()[:8]
    return candidate[:55] + "_" + digest


def concise_mcp_error(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return concise_mcp_error(exc.exceptions[0])
    message = str(exc).strip()
    return message or type(exc).__name__
