"""CLI-only research speed presets.

The presets deliberately tune request cost without imposing a wall-clock or phase ceiling on an
investigation.  Long research may still continue for hours; each individual model round simply
uses a smaller, purpose-selected tool schema set and a bounded response budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from maldroid.llama_client import ReasoningLevel


class SpeedMode(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


@dataclass(frozen=True)
class SpeedPreset:
    reasoning_level: ReasoningLevel | None
    response_token_cap: int | None
    tool_schema_budget: int
    description: str


SPEED_PRESETS: dict[SpeedMode, SpeedPreset] = {
    SpeedMode.FAST: SpeedPreset(
        reasoning_level="low",
        response_token_cap=1024,
        tool_schema_budget=14,
        description="Shortest model rounds for quick daily inspection and focused questions.",
    ),
    SpeedMode.BALANCED: SpeedPreset(
        reasoning_level="medium",
        response_token_cap=2048,
        tool_schema_budget=20,
        description="Responsive default with enough depth for normal static research.",
    ),
    SpeedMode.DEEP: SpeedPreset(
        reasoning_level=None,
        response_token_cap=None,
        tool_schema_budget=32,
        description="Full configured reasoning and response budget for difficult investigations.",
    ),
}


def speed_preset(mode: SpeedMode | str) -> SpeedPreset:
    return SPEED_PRESETS[SpeedMode(mode)]
