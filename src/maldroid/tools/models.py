"""Tool registration and runtime context types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from maldroid.case_manager import Case, CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.paths import PathPolicy

MCP_TOOL_PREFIX = "MalDroid_"


def mcp_tool_name(name: str) -> str:
    """Return the public MCP name for one MalDroid-managed tool."""
    return name if name.startswith(MCP_TOOL_PREFIX) else MCP_TOOL_PREFIX + name


@dataclass
class ToolContext:
    config: AppConfig
    case: Case
    case_manager: CaseManager
    investigation: InvestigationManager
    path_policy: PathPolicy

    def read_path(self, value: str) -> Path:
        return self.path_policy.resolve_read(value)

    def output_directory(self) -> Path:
        directory = self.case.root / "tool-output"
        directory.mkdir(parents=True, exist_ok=True)
        return directory


ToolHandler = Callable[[ToolContext, BaseModel], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    profile: str
    description: str
    arguments_model: type[BaseModel]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }
