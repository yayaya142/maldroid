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
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    description: str = Field(
        default="Supporting evidence",
        min_length=1,
        max_length=2000,
    )
    tool: str | None = None


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
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    status: Literal["open", "completed"] = "open"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class InvestigationNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    kind: Literal["research_note", "decision", "hypothesis", "user_note"] = "research_note"
    title: str | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class InvestigationCheckpoint(BaseModel):
    """Typed continuity record; operational logs belong in session/audit streams."""

    model_config = ConfigDict(extra="forbid")
    id: str
    objective: str = Field(min_length=1, max_length=12000)
    completed_work: list[str] = Field(default_factory=list, max_length=50)
    evidence_learned: list[str] = Field(default_factory=list, max_length=50)
    findings_changed: list[str] = Field(default_factory=list, max_length=50)
    todos_changed: list[str] = Field(default_factory=list, max_length=50)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=50)
    uncertainty: list[str] = Field(default_factory=list, max_length=50)
    next_action: str | None = Field(default=None, max_length=4000)
    status: Literal["in_progress", "complete", "blocked"] = "in_progress"
    phase: int | None = Field(default=None, ge=1)
    automatic: bool = False
    created_at: str = Field(default_factory=now_iso)

    @model_validator(mode="after")
    def meaningful(self) -> InvestigationCheckpoint:
        substantive = (
            self.completed_work
            or self.evidence_learned
            or self.findings_changed
            or self.todos_changed
            or self.unresolved_questions
        )
        if not substantive:
            raise ValueError("checkpoint must contain substantive research progress or open work")
        if self.status != "complete" and not self.next_action:
            raise ValueError("next_action is required unless the checkpoint is complete")
        return self


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
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    todos: list[TodoItem] = Field(default_factory=list)
    notes: list[InvestigationNote] = Field(default_factory=list)
    checkpoints: list[InvestigationCheckpoint] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    knowledge_documents_used: list[str] = Field(default_factory=list)
    external_tool_versions: dict[str, str] = Field(default_factory=dict)
    indexes: dict[str, dict[str, Any]] = Field(default_factory=dict)


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
