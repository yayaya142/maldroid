"""Validated, bounded, and audited in-process tool dispatch."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from maldroid.io_utils import append_jsonl, atomic_write_json
from maldroid.models import ToolError, ToolResult, now_iso
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import ToolRegistry


class ToolDispatcher:
    def __init__(self, registry: ToolRegistry, context: ToolContext):
        self.registry = registry
        self.context = context

    def execute(self, name: str, raw_arguments: str | dict[str, Any]) -> ToolResult:
        started = now_iso()
        tool = self.registry.get(name)
        if tool is None:
            return self._error(name, started, "unknown_tool", f"Unknown tool: {name}")
        if tool not in self.registry.enabled(self.context.case.state.active_profile):
            return self._error(
                name,
                started,
                "disabled_tool",
                f"Tool is not enabled for the active profile: {name}",
            )
        try:
            decoded = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            arguments = tool.arguments_model.model_validate(decoded)
            data = tool.handler(self.context, arguments)
            result = self._limit_output(data)
        except json.JSONDecodeError as exc:
            result = ToolResult(
                status="error",
                error=ToolError(code="invalid_json", message=f"Invalid tool arguments: {exc}"),
            )
        except ValidationError as exc:
            result = ToolResult(
                status="error",
                error=ToolError(
                    code="invalid_arguments",
                    message="Tool arguments failed schema validation.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        except Exception as exc:
            result = ToolResult(
                status="error",
                error=ToolError(code="execution_error", message=str(exc)),
            )
        self._audit(name, started, result)
        return result

    def _limit_output(self, data: Any) -> ToolResult:
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        limit = self.context.config.limits.max_tool_output_characters
        if len(serialized) <= limit:
            return ToolResult(status="completed", data=data)
        name = datetime.now().astimezone().strftime("tool-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        target = self.context.output_directory() / f"{name}.json"
        atomic_write_json(target, data)
        return ToolResult(
            status="completed",
            data={"preview": serialized[:limit], "total_characters": len(serialized)},
            truncated=True,
            output_file=target.relative_to(self.context.case.root).as_posix(),
        )

    def _error(self, name: str, started: str, code: str, message: str) -> ToolResult:
        result = ToolResult(status="error", error=ToolError(code=code, message=message))
        self._audit(name, started, result)
        return result

    def _audit(self, name: str, started: str, result: ToolResult) -> None:
        append_jsonl(
            self.context.case.internal / "logs" / "tools.jsonl",
            {
                "started_at": started,
                "completed_at": now_iso(),
                "tool": name,
                "status": result.status,
                "error_code": result.error.code if result.error else None,
                "truncated": result.truncated,
                "output_file": result.output_file,
            },
        )
