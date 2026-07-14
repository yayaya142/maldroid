"""Persistent domain models for cases, evidence, and investigation state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    description: str
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
    evidence: list[EvidenceReference] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


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
