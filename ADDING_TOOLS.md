# Adding a Tool

1. Create a strict Pydantic argument model with `extra="forbid"`.
2. Write a deterministic handler accepting `ToolContext` and the validated model.
3. Resolve every input path through `context.read_path`; never use a model-supplied absolute path.
4. Use `context.output_directory()` for large output.
5. Use an allowlisted argument array, timeout, and `shell=False` for any static external utility.
6. Register a unique name, concise description, argument model, handler, and one profile.
7. Add unit, path-adversarial, output-limit, profile-filter, and failure tests.
8. Document parameters, result, accuracy, and safety in `TOOLS.md`.
9. Confirm `/tools` displays it only in core or the assigned profile.
10. Confirm MCP `tools/list` publishes the generated JSON Schema only for the correct profile.
11. Confirm MCP `tools/call` returns the expected structured `ToolResult` and audit event.
12. Confirm a fake model call executes through `McpToolClient` and returns to the model.
13. Update status, changelog, and handoff.

Complete example:

```python
from pydantic import BaseModel, ConfigDict, Field

from maldroid.tools.models import ToolContext, ToolDefinition


class CountTermInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    term: str = Field(min_length=1, max_length=200)


def count_term(context: ToolContext, arguments: BaseModel) -> dict[str, object]:
    values = CountTermInput.model_validate(arguments)
    path = context.read_path(values.path)
    count = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            count += line.count(values.term)
    return {"path": values.path, "term": values.term, "count": count}


registry.register(
    ToolDefinition(
        name="count_term",
        profile="core",
        description="Count exact term occurrences in a case text file.",
        arguments_model=CountTermInput,
        handler=count_term,
    )
)
```

Do not add shell, deletion, arbitrary write, network, upload, sample execution, or dynamic-analysis
tools.
