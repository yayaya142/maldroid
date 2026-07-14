"""Persistent findings, notes, and TODO operations."""

from __future__ import annotations

from pathlib import Path

from maldroid.case_manager import Case, CaseManager
from maldroid.exceptions import CaseError
from maldroid.models import EvidenceReference, Finding, InvestigationNote, TodoItem, now_iso


class InvestigationManager:
    def __init__(self, case_manager: CaseManager):
        self.case_manager = case_manager

    def save_note(
        self, case: Case, text: str, evidence: list[EvidenceReference] | None = None
    ) -> InvestigationNote:
        note = InvestigationNote(
            id=_next_id("NOTE", [item.id for item in case.state.notes]),
            text=text,
            evidence=evidence or [],
        )
        case.state.notes.append(note)
        self.case_manager.save(case)
        self._append_markdown(case.root / "notes" / "CASE.md", f"## {note.id}\n\n{text}\n")
        return note

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
        self.case_manager.save(case)
        self._render_findings(case)
        return finding

    def update_finding(self, case: Case, finding_id: str, changes: dict[str, object]) -> Finding:
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
        self.case_manager.save(case)
        self._render_findings(case)
        return updated

    def update_todo(self, case: Case, action: str, text_or_id: str) -> TodoItem | None:
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
        self.case_manager.save(case)
        self._render_todos(case)
        return item

    @staticmethod
    def _append_markdown(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Case Notes\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content + "\n")

    @staticmethod
    def _render_findings(case: Case) -> None:
        path = case.root / "notes" / "FINDINGS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        sections = ["# Findings", ""]
        for finding in case.state.findings:
            sections.extend(
                [
                    f"## {finding.id}: {finding.title}",
                    "",
                    f"- Status: {finding.status}",
                    f"- Confidence: {finding.confidence}",
                    f"- Severity: {finding.severity}",
                    "",
                    finding.summary,
                    "",
                ]
            )
        path.write_text("\n".join(sections), encoding="utf-8")

    @staticmethod
    def _render_todos(case: Case) -> None:
        path = case.root / "notes" / "TODO.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# TODO", ""]
        for item in case.state.todos:
            marker = "x" if item.status == "completed" else " "
            lines.append(f"- [{marker}] {item.id}: {item.text}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _next_id(prefix: str, existing: list[str]) -> str:
    numbers = []
    for value in existing:
        try:
            numbers.append(int(value.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"
