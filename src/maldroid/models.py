"""Persistent domain models for cases, evidence, and investigation state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maldroid.constants import CASE_SCHEMA_VERSION, STATE_SCHEMA_VERSION


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    case_path: str
    source_path: str
    mode: Literal["symlink", "copy"]
    size: int
    modified_at: str
    registered_at: str = Field(default_factory=now_iso)
    sha256: str | None = None
    source_resolved_path: str


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="Case-relative path to the evidence file")
    start_line: int | None = Field(default=None, ge=1, description="First line number (1-indexed)")
    end_line: int | None = Field(default=None, ge=1, description="Last line number (inclusive)")
    start_offset: int | None = Field(default=None, ge=0, description="Start byte offset")
    end_offset: int | None = Field(default=None, ge=0, description="End byte offset")
    description: str = Field(
        default="",
        description="Human-readable description of what this evidence shows (optional; a default is generated from path if omitted)",
    )
    tool: str | None = Field(
        default=None, description="Name of the tool that produced this reference"
    )

    @model_validator(mode="after")
    def _fill_default_description(self) -> EvidenceReference:
        if not self.description:
            self.description = f"Reference to {self.path}"
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    summary: str
    confidence: Literal["low", "medium", "high"] = "medium"
    severity: Literal["informational", "low", "medium", "high", "critical"] = "medium"
    status: Literal["tentative", "confirmed", "rejected", "resolved"] = "tentative"
    evidence: list[EvidenceReference] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    client_mutation_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    status: Literal["open", "completed", "blocked"] = "open"
    priority: Literal["low", "medium", "high"] = "medium"
    dependencies: list[str] = Field(default_factory=list, description="IDs of blocking TODOs")
    owner: str | None = None
    client_mutation_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class InvestigationNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["general", "research_note", "checkpoint", "decision", "hypothesis", "tool_error", "user_note"] = "research_note"
    text: str
    evidence: list[EvidenceReference] = Field(default_factory=list)
    status: Literal["active", "archived"] = "active"

    # Checkpoint fields
    objective: str | None = None
    completed_work: str | None = None
    evidence_learned: str | None = None
    findings_changed: str | None = None
    todos_changed: str | None = None
    failed_approaches: str | None = None
    unresolved_questions: str | None = None
    uncertainty: str | None = None
    next_action: str | None = None

    # Link state records
    related_finding_ids: list[str] = Field(default_factory=list)
    related_todo_ids: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)
    session_id: str | None = None
    tool_call_ids: list[str] = Field(default_factory=list)
    state_revision: int = 0
    phase: str | None = None

    client_mutation_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @model_validator(mode="after")
    def validate_checkpoint(self) -> InvestigationNote:
        if self.kind == "checkpoint":
            missing = [
                field for field in (
                    "objective", "completed_work", "evidence_learned", "findings_changed",
                    "todos_changed", "failed_approaches", "unresolved_questions",
                    "uncertainty", "next_action"
                )
                if getattr(self, field) is None
            ]
            if missing:
                raise ValueError(f"Checkpoint is missing required fields: {', '.join(missing)}")
        return self

class StateTelemetry(BaseModel):
    orphan_references: int = 0
    duplicate_findings: int = 0
    stale_todos: int = 0
    automatic_fallback_usage: int = 0
    failed_mutations: int = 0
    view_degradations: int = 0


class CaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = CASE_SCHEMA_VERSION
    case_id: str
    name: str
    root: str
    managed: bool
    created_at: str = Field(default_factory=now_iso)
    last_opened_at: str = Field(default_factory=now_iso)


class CaseState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = STATE_SCHEMA_VERSION
    active_profile: str = "generic"
    context_size: int = 65536
    model_path: str = ""
    summary: str = ""
    state_revision: int = 0
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    todos: list[TodoItem] = Field(default_factory=list)
    notes: list[InvestigationNote] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    knowledge_documents_used: list[str] = Field(default_factory=list)
    external_tool_versions: dict[str, str] = Field(default_factory=dict)
    indexes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    telemetry: StateTelemetry = Field(default_factory=StateTelemetry)


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    timestamp: str = Field(default_factory=now_iso)
    type: str
    role: str | None = None
    content: Any = None


class ToolError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    status: Literal["completed", "error"]
    data: Any = None
    error: ToolError | None = None
    truncated: bool = False
    output_file: str | None = None
