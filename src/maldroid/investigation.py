"""Persistent findings, notes, and TODO operations."""

from __future__ import annotations

import re
from contextlib import suppress

from maldroid.case_manager import Case, CaseManager
from maldroid.exceptions import CaseError
from maldroid.io_utils import atomic_write_text
from maldroid.models import (
    CaseState,
    EvidenceReference,
    Finding,
    InvestigationCheckpoint,
    InvestigationNote,
    TodoItem,
    now_iso,
)


class InvestigationManager:
    def __init__(self, case_manager: CaseManager):
        self.case_manager = case_manager

    def save_note(
        self,
        case: Case,
        text: str,
        evidence: list[EvidenceReference] | None = None,
        *,
        kind: str = "research_note",
        title: str | None = None,
    ) -> InvestigationNote:
        if kind != "user_note":
            _validate_research_note(text)
        previous = case.state.model_copy(deep=True)
        note = InvestigationNote(
            id=_next_id("NOTE", [item.id for item in case.state.notes]),
            text=text,
            kind=kind,  # type: ignore[arg-type]
            title=title,
            evidence=evidence or [],
        )
        case.state.notes.append(note)
        self._persist_mutation(case, previous)
        return note

    def save_checkpoint(
        self,
        case: Case,
        *,
        objective: str,
        completed_work: list[str] | None = None,
        evidence_learned: list[str] | None = None,
        findings_changed: list[str] | None = None,
        todos_changed: list[str] | None = None,
        unresolved_questions: list[str] | None = None,
        uncertainty: list[str] | None = None,
        next_action: str | None = None,
        status: str = "in_progress",
        phase: int | None = None,
        automatic: bool = False,
    ) -> InvestigationCheckpoint:
        previous = case.state.model_copy(deep=True)
        checkpoint = InvestigationCheckpoint(
            id=_next_id("CHECK", [item.id for item in case.state.checkpoints]),
            objective=objective,
            completed_work=completed_work or [],
            evidence_learned=evidence_learned or [],
            findings_changed=findings_changed or [],
            todos_changed=todos_changed or [],
            unresolved_questions=unresolved_questions or [],
            uncertainty=uncertainty or [],
            next_action=next_action,
            status=status,  # type: ignore[arg-type]
            phase=phase,
            automatic=automatic,
        )
        case.state.checkpoints.append(checkpoint)
        self._persist_mutation(case, previous)
        return checkpoint

    def save_finding(
        self,
        case: Case,
        title: str,
        summary: str,
        confidence: str = "medium",
        severity: str = "medium",
        status: str = "tentative",
        evidence: list[EvidenceReference] | None = None,
        tags: list[str] | None = None,
    ) -> Finding:
        previous = case.state.model_copy(deep=True)
        finding = Finding(
            id=_next_id("FIND", [item.id for item in case.state.findings]),
            title=title,
            summary=summary,
            confidence=confidence,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            evidence=evidence or [],
            tags=tags or [],
        )
        case.state.findings.append(finding)
        self._persist_mutation(case, previous)
        return finding

    def update_finding(self, case: Case, finding_id: str, changes: dict[str, object]) -> Finding:
        previous = case.state.model_copy(deep=True)
        finding = next((item for item in case.state.findings if item.id == finding_id), None)
        if finding is None:
            raise CaseError(f"Finding not found: {finding_id}")
        allowed = {"title", "summary", "confidence", "severity", "status", "tags", "evidence"}
        unknown = set(changes) - allowed
        if unknown:
            raise CaseError("Unsupported finding fields: " + ", ".join(sorted(unknown)))
        updated = Finding.model_validate(
            {**finding.model_dump(), **changes, "updated_at": now_iso()}
        )
        index = case.state.findings.index(finding)
        case.state.findings[index] = updated
        self._persist_mutation(case, previous)
        return updated

    def update_todo(self, case: Case, action: str, text_or_id: str) -> TodoItem | None:
        previous = case.state.model_copy(deep=True)
        item: TodoItem | None
        if action == "add":
            item = TodoItem(
                id=_next_id("TODO", [todo.id for todo in case.state.todos]), text=text_or_id
            )
            case.state.todos.append(item)
        else:
            item = next((todo for todo in case.state.todos if todo.id == text_or_id), None)
            if item is None:
                raise CaseError(f"TODO item not found: {text_or_id}")
            if action == "complete":
                item.status = "completed"
                item.updated_at = now_iso()
            elif action == "reopen":
                item.status = "open"
                item.updated_at = now_iso()
            elif action == "remove":
                case.state.todos.remove(item)
                item = None
            else:
                raise CaseError(f"Unsupported TODO action: {action}")
        self._persist_mutation(case, previous)
        return item

    def _persist_mutation(self, case: Case, previous: CaseState) -> None:
        """Persist canonical state and deterministic views, rolling back on failure."""
        try:
            self.case_manager.save(case)
            self._render_views(case)
        except Exception as exc:
            case.state = previous
            with suppress(Exception):
                self.case_manager.save(case)
                self._render_views(case)
            raise CaseError(
                f"Could not persist investigation data; change rolled back: {exc}"
            ) from exc

    @classmethod
    def _render_views(cls, case: Case) -> None:
        cls._render_notes(case)
        cls._render_findings(case)
        cls._render_todos(case)
        cls._render_checkpoints(case)

    @staticmethod
    def _render_notes(case: Case) -> None:
        sections = ["# Case Notes", ""]
        for note in case.state.notes:
            sections.extend(
                [
                    f"## {note.id}: {note.title or note.kind.replace('_', ' ').title()}",
                    "",
                    f"_Kind: {note.kind} · Created: {note.created_at}_",
                    "",
                    note.text,
                    "",
                ]
            )
            if note.evidence:
                sections.extend(["Evidence:", ""])
                sections.extend(_render_evidence(reference) for reference in note.evidence)
                sections.append("")
        atomic_write_text(case.root / "notes" / "CASE.md", "\n".join(sections))

    @staticmethod
    def _render_findings(case: Case) -> None:
        sections = ["# Findings", ""]
        for finding in case.state.findings:
            sections.extend(
                [
                    f"## {finding.id}: {finding.title}",
                    "",
                    f"- Status: {finding.status}",
                    f"- Confidence: {finding.confidence}",
                    f"- Severity: {finding.severity}",
                    f"- Created: {finding.created_at}",
                    f"- Updated: {finding.updated_at}",
                    f"- Tags: {', '.join(finding.tags) if finding.tags else 'none'}",
                    "",
                    finding.summary,
                    "",
                ]
            )
            if finding.evidence:
                sections.extend(["Evidence:", ""])
                sections.extend(_render_evidence(reference) for reference in finding.evidence)
                sections.append("")
        atomic_write_text(case.root / "notes" / "FINDINGS.md", "\n".join(sections))

    @staticmethod
    def _render_todos(case: Case) -> None:
        lines = ["# TODO", ""]
        for item in case.state.todos:
            marker = "x" if item.status == "completed" else " "
            lines.append(f"- [{marker}] {item.id}: {item.text}")
        atomic_write_text(case.root / "notes" / "TODO.md", "\n".join(lines) + "\n")

    @staticmethod
    def _render_checkpoints(case: Case) -> None:
        sections = ["# Research Checkpoints", ""]
        for item in case.state.checkpoints:
            sections.extend(
                [
                    f"## {item.id}: {item.status}",
                    "",
                    f"_Created: {item.created_at} · Phase: {item.phase or 'n/a'}"
                    f" · Automatic: {'yes' if item.automatic else 'no'}_",
                    "",
                    "### Objective",
                    "",
                    item.objective,
                    "",
                ]
            )
            for heading, values in (
                ("Completed work", item.completed_work),
                ("Evidence learned", item.evidence_learned),
                ("Findings changed", item.findings_changed),
                ("TODOs changed", item.todos_changed),
                ("Unresolved questions", item.unresolved_questions),
                ("Uncertainty", item.uncertainty),
            ):
                if values:
                    sections.extend([f"### {heading}", ""])
                    sections.extend(f"- {value}" for value in values)
                    sections.append("")
            if item.next_action:
                sections.extend(["### Next action", "", item.next_action, ""])
        atomic_write_text(case.root / "notes" / "CHECKPOINTS.md", "\n".join(sections))


def _next_id(prefix: str, existing: list[str]) -> str:
    numbers = []
    for value in existing:
        try:
            numbers.append(int(value.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def _render_evidence(reference: EvidenceReference) -> str:
    location = reference.path
    if reference.start_line is not None:
        location += f":{reference.start_line}"
        if reference.end_line is not None and reference.end_line != reference.start_line:
            location += f"-{reference.end_line}"
    elif reference.start_offset is not None:
        location += f"@{reference.start_offset}"
        if reference.end_offset is not None:
            location += f"-{reference.end_offset}"
    tool = f"; tool: {reference.tool}" if reference.tool else ""
    return f"- `{location}` — {reference.description}{tool}"


def _validate_research_note(text: str) -> None:
    operational = (
        r"\bMalDroid_[A-Za-z0-9_]+",
        r'"(?:tool|status|arguments|error)"\s*:',
        r"Automatic progress checkpoint",
        r"Evidence work performed:",
        r"Durable investigation state:",
        r"\btool (?:call|result|failed|executed)\b",
    )
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in operational):
        raise CaseError(
            "Research notes must contain durable analysis, decisions, or hypotheses; "
            "tool activity and errors belong in the session audit."
        )
