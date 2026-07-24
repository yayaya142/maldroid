"""Profile-aware tool registry."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from maldroid.exceptions import ToolExecutionError
from maldroid.tools.models import ToolContext, ToolDefinition, mcp_tool_name

TOOL_SEARCH_SYNONYMS: dict[str, tuple[str, ...]] = {
    "apk": ("archive", "zip", "manifest", "android"),
    "bundle": ("javascript", "source", "archive"),
    "code": ("source", "symbol", "dependencies", "references"),
    "decrypt": ("decode", "transform", "obfuscation", "python", "script"),
    "decoder": ("decode", "transform", "python", "script"),
    "database": ("sqlite", "table", "schema"),
    "db": ("sqlite", "table", "schema"),
    "hash": ("sha256", "fingerprint", "file"),
    "encrypted": ("obfuscation", "decode", "encoding", "entropy", "script"),
    "function": ("symbol", "declaration", "code", "context", "index"),
    "obfuscation": ("decode", "strings", "entropy", "source"),
    "reverse": ("source", "symbol", "native", "javascript"),
    "snippet": ("source", "code", "context"),
}


class ToolCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        definition = replace(definition, name=mcp_tool_name(definition.name))
        if definition.name in self._tools:
            raise ToolExecutionError(f"Duplicate tool name: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def enabled(self, profile: str) -> list[ToolDefinition]:
        return sorted(
            (
                tool
                for tool in self._tools.values()
                if tool.profile == "core" or tool.profile == profile
            ),
            key=lambda tool: tool.name,
        )

    def schemas(self, profile: str) -> list[dict[str, object]]:
        return [tool.schema() for tool in self.enabled(profile)]

    def schemas_for_names(self, profile: str, names: set[str]) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self.enabled(profile) if tool.name in names]

    def names(self, profile: str) -> list[str]:
        return [tool.name for tool in self.enabled(profile)]

    def search(self, profile: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        ranked: list[tuple[int, ToolDefinition]] = []
        for tool in self.enabled(profile):
            if tool.name == mcp_tool_name("search_tool_catalog"):
                continue
            score = tool_search_score(tool.schema(), query)
            if score:
                ranked.append((score, tool))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        return [
            {
                "name": tool.name,
                "scope": tool.profile,
                "description": tool.description,
                "score": score,
            }
            for score, tool in ranked[:limit]
        ]


def tool_search_score(schema: dict[str, Any], query: str) -> int:
    """Rank a compact tool schema against a natural-language capability query."""
    function = schema.get("function", {})
    name = str(function.get("name", "")).lower()
    description = str(function.get("description", "")).lower()
    parameters = json.dumps(function.get("parameters", {}), ensure_ascii=False).lower()
    raw_tokens = set(re.findall(r"[a-z0-9_+-]{2,}", query.lower()))
    tokens = set(raw_tokens)
    for token in raw_tokens:
        tokens.update(TOOL_SEARCH_SYNONYMS.get(token, ()))
    score = 0
    for token in tokens:
        if token in name:
            score += 8
        if token in description:
            score += 3
        if token in parameters:
            score += 1
    compact_query = " ".join(query.lower().split())
    if compact_query and compact_query in f"{name} {description}":
        score += 12
    return score


def _register_catalog_tool(registry: ToolRegistry) -> None:
    def search_catalog(_: ToolContext, arguments: BaseModel) -> dict[str, Any]:
        values = ToolCatalogInput.model_validate(arguments)
        # The active profile is validated again by the dispatcher. The closure sees the exact
        # registry published by the running MCP server, so catalogue results cannot invent tools.
        # The handler receives no filesystem authority and performs no evidence reads.
        profile = _.case.state.active_profile
        matches = registry.search(profile, values.query, values.limit)
        return {
            "query": values.query,
            "matches": matches,
            "available_next_round": bool(matches),
            "instruction": (
                "Matched tool schemas are loaded into the next model round. Choose the smallest "
                "relevant tool and do not repeat this search unchanged."
            ),
        }

    registry.register(
        ToolDefinition(
            "search_tool_catalog",
            "core",
            "Find and load static-research tools by capability without exposing every schema.",
            ToolCatalogInput,
            search_catalog,
        )
    )


def build_registry() -> ToolRegistry:
    from maldroid.tools.core.builtin import register_core_tools
    from maldroid.tools.core.code_analysis import register_code_analysis_tools
    from maldroid.tools.core.research import register_research_tools
    from maldroid.tools.core.triage import register_triage_tools
    from maldroid.tools.profiles.frameworks import register_framework_tools
    from maldroid.tools.profiles.native import register_native_tools
    from maldroid.tools.profiles.react_native import register_react_native_tools

    registry = ToolRegistry()
    register_core_tools(registry)
    register_triage_tools(registry)
    register_research_tools(registry)
    register_code_analysis_tools(registry)
    register_react_native_tools(registry)
    register_native_tools(registry)
    register_framework_tools(registry)
    _register_catalog_tool(registry)
    return registry
