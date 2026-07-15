"""Shared investigation runtime used by terminal and web surfaces."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.config import AppConfig
from maldroid.external_mcp import ExternalMcpRegistryManager, ExternalMcpRuntime
from maldroid.investigation import InvestigationManager
from maldroid.llama_client import LocalLlamaClient
from maldroid.logging_config import configure_case_logging
from maldroid.mcp_server import MalDroidMcpServer, McpToolClient
from maldroid.paths import PathPolicy
from maldroid.process_manager import LlamaServerProcess
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import ToolRegistry, build_registry

RuntimeEventHandler = Callable[[str, dict[str, Any]], None]


class WorkspaceRuntime:
    """Own llama.cpp, case MCP, external MCP, sessions, and the agent as one unit."""

    def __init__(
        self,
        config: AppConfig,
        case: Case,
        manager: CaseManager,
        *,
        llama_port: int | None = None,
        mcp_port: int | None = None,
        auto_profile: bool = True,
        event_handler: RuntimeEventHandler | None = None,
    ) -> None:
        self.config = config
        self.case = case
        self.manager = manager
        self.llama_port = llama_port
        self.mcp_port = mcp_port
        self.auto_profile = auto_profile
        self.event_handler = event_handler
        self.logger = configure_case_logging(case.root)
        self.server = LlamaServerProcess(config, case.root)
        self.registry: ToolRegistry | None = None
        self.local_dispatcher: ToolDispatcher | None = None
        self.dispatcher: McpToolClient | None = None
        self.mcp_server: MalDroidMcpServer | None = None
        self.mcp_endpoint = ""
        self.sessions: SessionManager | None = None
        self.external_mcp: ExternalMcpRuntime | None = None
        self.agent: MalDroidAgent | None = None

    def start(self) -> WorkspaceRuntime:
        self.logger.info("Starting shared local workspace runtime")
        command = self.server.start(
            self.case.state.context_size,
            self.llama_port,
            explicit_port=self.llama_port is not None,
        )
        client = LocalLlamaClient(
            self.server.base_url,
            command.api_key,
            Path(self.config.llama.model).name,
            self.config.llama.temperature,
            self.config.llama.max_response_tokens,
            self.config.llama.reasoning_level,
            repetition_recovery_enabled=self.config.llama.repetition_recovery_enabled,
        )
        self.registry, self.local_dispatcher = build_tool_runtime(
            self.config, self.case, self.manager
        )
        self.mcp_server = MalDroidMcpServer(
            self.config,
            self.registry,
            self.local_dispatcher,
            model_server_port=command.port,
        )
        self.mcp_endpoint = self.mcp_server.start(self.mcp_port)
        self.dispatcher = McpToolClient(
            self.mcp_endpoint,
            timeout_seconds=self.config.limits.command_timeout_seconds,
        )
        previous = SessionManager.load_latest_summary(self.case)
        self.sessions = SessionManager(self.case, self.manager)
        self.external_mcp = ExternalMcpRuntime(self.config, self.case, ExternalMcpRegistryManager())
        for status in self.external_mcp.refresh():
            self.sessions.record("external_mcp_connection", content=status)
            self._emit("external_mcp_connection", **status)
        self.agent = MalDroidAgent(
            self.config,
            self.case,
            client,
            self.registry,
            self.dispatcher,
            self.sessions,
            previous,
            event_handler=self.event_handler,
            auto_profile_enabled=self.auto_profile,
            external_mcp=self.external_mcp,
        )
        self._emit("runtime_ready", mcp_endpoint=self.mcp_endpoint)
        return self

    def stop(self, compact: bool = True) -> None:
        if compact and self.agent is not None and self.sessions is not None:
            try:
                self.agent.compact()
            except Exception as exc:
                self.sessions.save_summary(
                    self.case.state.summary or f"Session ended. Summary failed: {exc}"
                )
        if self.mcp_server is not None:
            self.mcp_server.stop()
        self.server.stop()
        self.logger.info("Shared local workspace runtime stopped")
        self.agent = None

    def _emit(self, event: str, **data: Any) -> None:
        if self.event_handler is not None:
            self.event_handler(event, data)


def build_tool_runtime(
    config: AppConfig, case: Case, manager: CaseManager
) -> tuple[ToolRegistry, ToolDispatcher]:
    registry = build_registry()
    investigation = InvestigationManager(manager)
    evidence_sources = {item.case_path: item.source_resolved_path for item in case.state.evidence}
    context = ToolContext(
        config=config,
        case=case,
        case_manager=manager,
        investigation=investigation,
        path_policy=PathPolicy(case.root, evidence_sources),
    )
    return registry, ToolDispatcher(registry, context)
