"""Profile-aware tool registry."""

from __future__ import annotations

from dataclasses import replace

from maldroid.exceptions import ToolExecutionError
from maldroid.tools.models import ToolDefinition, mcp_tool_name


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

    def names(self, profile: str) -> list[str]:
        return [tool.name for tool in self.enabled(profile)]


def build_registry() -> ToolRegistry:
    from maldroid.tools.core.builtin import register_core_tools
    from maldroid.tools.profiles.frameworks import register_framework_tools
    from maldroid.tools.profiles.native import register_native_tools
    from maldroid.tools.profiles.react_native import register_react_native_tools

    registry = ToolRegistry()
    register_core_tools(registry)
    register_react_native_tools(registry)
    register_native_tools(registry)
    register_framework_tools(registry)
    return registry
