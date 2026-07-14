"""Persistent findings, notes, and TODO operations.

Persistence contract (REL-012):
  Every mutation follows: validate → render → save → return.
  If rendering raises, the state object is restored and no file is written.
  If the final save raises, the in-memory state is also restored so
  the caller sees a clean error and can retry safely.
"""

from __future__ import annotations

from pathlib import Path

from maldroid.case_manager import Case, CaseManager
from maldroid.exceptions import CaseError
from maldroid.models import EvidenceReference, Finding, InvestigationNote, TodoItem, now_iso


class InvestigationManager:
    def __init__(self, case_manager: CaseManager):
        self.case_manager = case_manager

    def save_note(
        self,
        case: Case,
        text: str,
        evidence: list[EvidenceReference] | None = None,
        client_mutation_id: str | None = None,
    ) -> InvestigationNote:
        if client_mutation_id:
            for existing in case.state.notes:
                if existing.client_mutation_id == client_mutation_id:
                    return existing

        note = InvestigationNote(
            id=_next_id("NOTE", [item.id for item in case.state.notes]),
            text=text,
            evidence=evidence or [],
            client_mutation_id=client_mutation_id,
        )
        # Build Markdown first — if this fails nothing is persisted
        note_md = _render_note_section(note)
        # Append to state (in-memory only)
        case.state.notes.append(note)
        # Persist state and Markdown atomically by order: state then file
        try:
            self.case_manager.save(case)
            self._append_markdown(case.root / "notes" / "CASE.md", note_md)
        except Exception:
            # Roll back in-memory state so the caller sees a clean failure
            case.state.notes.pop()
            raise
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
        client_mutation_id: str | None = None,
    ) -> Finding:
        if client_mutation_id:
            for existing in case.state.findings:
                if existing.client_mutation_id == client_mutation_id:
                    return existing

        # Near-duplicate detection
        title_lower = title.lower().strip()
        for existing in case.state.findings:
            if existing.title.lower().strip() == title_lower:
                raise CaseError(f"Duplicate finding detected: a finding with the title '{title}' already exists ({existing.id}). Use update_finding instead.")

        finding = Finding(
            id=_next_id("FIND", [item.id for item in case.state.findings]),
            title=title,
            summary=summary,
            confidence=confidence,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            evidence=evidence or [],
            tags=tags or [],
            client_mutation_id=client_mutation_id,
        )
        # Build the full Markdown representation first — fail before touching state
        updated_findings = case.state.findings + [finding]
        findings_md = _render_findings_document(updated_findings)
        # Commit to in-memory state
        case.state.findings.append(finding)
        # Persist — roll back on failure
        try:
            self.case_manager.save(case)
            path = case.root / "notes" / "FINDINGS.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            from maldroid.io_utils import atomic_write_text

            atomic_write_text(path, findings_md)
        except Exception:
            case.state.findings.pop()
            raise
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
        # Pre-render before mutating state
        preview_findings = list(case.state.findings)
        preview_findings[index] = updated
        findings_md = _render_findings_document(preview_findings)
        # Commit
        case.state.findings[index] = updated
        try:
            self.case_manager.save(case)
            path = case.root / "notes" / "FINDINGS.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            from maldroid.io_utils import atomic_write_text

            atomic_write_text(path, findings_md)
        except Exception:
            case.state.findings[index] = finding
            raise
        return updated

    def update_todo(
        self,
        case: Case,
        action: str,
        text_or_id: str,
        client_mutation_id: str | None = None,
    ) -> TodoItem | None:
        item: TodoItem | None
        original_todos = list(case.state.todos)
        if action == "add":
            if client_mutation_id:
                for existing in case.state.todos:
                    if existing.client_mutation_id == client_mutation_id:
                        return existing
            
            # Near-duplicate detection for TODOs
            text_lower = text_or_id.lower().strip()
            for existing in case.state.todos:
                if existing.text.lower().strip() == text_lower and existing.status == "open":
                    raise CaseError(f"Duplicate TODO detected: an open TODO with the text '{text_or_id}' already exists ({existing.id}).")

            item = TodoItem(
                id=_next_id("TODO", [todo.id for todo in case.state.todos]),
                text=text_or_id,
                client_mutation_id=client_mutation_id,
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
        try:
            self.case_manager.save(case)
            self._render_todos(case)
        except Exception:
            case.state.todos[:] = original_todos
            raise
        return item

    def list_findings(
        self,
        case: Case,
        status: str | None = None,
        confidence: str | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        """Return a paginated list of findings with optional filters."""
        findings = list(case.state.findings)
        if status:
            findings = [f for f in findings if f.status == status]
        if confidence:
            findings = [f for f in findings if f.confidence == confidence]
        if tag:
            findings = [f for f in findings if tag in f.tags]
        total = len(findings)
        start = (page - 1) * page_size
        page_items = findings[start : start + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "findings": [f.model_dump() for f in page_items],
        }

    def get_finding(self, case: Case, finding_id: str) -> Finding:
        """Return a single finding by ID."""
        finding = next((f for f in case.state.findings if f.id == finding_id), None)
        if finding is None:
            raise CaseError(f"Finding not found: {finding_id}")
        return finding

    def list_notes(self, case: Case, page: int = 1, page_size: int = 20) -> dict[str, object]:
        """Return a paginated list of investigation notes."""
        notes = list(case.state.notes)
        total = len(notes)
        start = (page - 1) * page_size
        page_items = notes[start : start + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "notes": [n.model_dump() for n in page_items],
        }

    def get_note(self, case: Case, note_id: str) -> InvestigationNote:
        """Return a single note by ID."""
        note = next((n for n in case.state.notes if n.id == note_id), None)
        if note is None:
            raise CaseError(f"Note not found: {note_id}")
        return note

    def list_todos(
        self,
        case: Case,
        include_completed: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        """Return a paginated list of TODO items."""
        todos = list(case.state.todos)
        if not include_completed:
            todos = [t for t in todos if t.status == "open"]
        total = len(todos)
        start = (page - 1) * page_size
        page_items = todos[start : start + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "todos": [t.model_dump() for t in page_items],
        }

    def get_case_revision(self, case: Case) -> dict[str, object]:
        """Return a compact case state digest for verification."""
        return {
            "active_profile": case.state.active_profile,
            "finding_count": len(case.state.findings),
            "note_count": len(case.state.notes),
            "open_todo_count": sum(1 for t in case.state.todos if t.status == "open"),
            "completed_todo_count": sum(1 for t in case.state.todos if t.status == "completed"),
            "evidence_count": len(case.state.evidence),
        }

    def rebuild_views(self, case: Case) -> dict[str, object]:
        """Rebuild all human-readable Markdown views from canonical state."""
        from maldroid.io_utils import atomic_write_text

        results: dict[str, object] = {}

        # Rebuild FINDINGS.md
        findings_path = case.root / "notes" / "FINDINGS.md"
        findings_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(findings_path, _render_findings_document(case.state.findings))
        results["findings_md"] = "rebuilt"

        # Rebuild TODO.md
        todos_path = case.root / "notes" / "TODO.md"
        atomic_write_text(todos_path, _render_todos_document(case.state.todos))
        results["todo_md"] = "rebuilt"

        # Rebuild CASE.md (notes)
        notes_path = case.root / "notes" / "CASE.md"
        sections = ["# Case Notes", ""]
        for note in case.state.notes:
            sections.append(_render_note_section(note))
        atomic_write_text(notes_path, "\n".join(sections) + "\n")
        results["case_md"] = "rebuilt"

        return results

    @staticmethod
    def _append_markdown(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Case Notes\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content + "\n")

    @staticmethod
    def _render_findings(case: Case) -> None:
        """Re-render FINDINGS.md from current case state (legacy method kept for compatibility)."""
        from maldroid.io_utils import atomic_write_text

        path = case.root / "notes" / "FINDINGS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, _render_findings_document(case.state.findings))

    @staticmethod
    def _render_todos(case: Case) -> None:
        from maldroid.io_utils import atomic_write_text

        path = case.root / "notes" / "TODO.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, _render_todos_document(case.state.todos))


# ---------------------------------------------------------------------------
# Private rendering helpers
# ---------------------------------------------------------------------------


def _render_note_section(note: InvestigationNote) -> str:
    """Render a single note as a Markdown section with timestamps and evidence."""
    lines = [
        f"## {note.id}",
        "",
        f"*Created: {note.created_at}*",
        "",
        note.text,
    ]
    if note.evidence:
        lines += ["", "**Evidence references:**"]
        for ref in note.evidence:
            line_info = ""
            if ref.start_line is not None:
                line_info = f" (lines {ref.start_line}–{ref.end_line or ref.start_line})"
            tool_info = f" via `{ref.tool}`" if ref.tool else ""
            lines.append(f"- `{ref.path}`{line_info}{tool_info}: {ref.description}")
    lines.append("")
    return "\n".join(lines)


def _render_findings_document(findings: list) -> str:
    """Render the full FINDINGS.md document with all fields including evidence and tags."""
    sections = ["# Findings", ""]
    for finding in findings:
        sections += [
            f"## {finding.id}: {finding.title}",
            "",
            f"- **Status**: {finding.status}",
            f"- **Confidence**: {finding.confidence}",
            f"- **Severity**: {finding.severity}",
            f"- **Created**: {finding.created_at}",
            f"- **Updated**: {finding.updated_at}",
        ]
        if finding.tags:
            tags_str = ", ".join(f"`{t}`" for t in finding.tags)
            sections.append(f"- **Tags**: {tags_str}")
        sections += ["", finding.summary, ""]
        if finding.evidence:
            sections.append("**Evidence:**")
            for ref in finding.evidence:
                line_info = ""
                if ref.start_line is not None:
                    line_info = f" (lines {ref.start_line}–{ref.end_line or ref.start_line})"
                elif ref.start_offset is not None:
                    line_info = (
                        f" (offsets {ref.start_offset}–{ref.end_offset or ref.start_offset})"
                    )
                tool_info = f" via `{ref.tool}`" if ref.tool else ""
                sections.append(f"- `{ref.path}`{line_info}{tool_info}: {ref.description}")
            sections.append("")
    return "\n".join(sections)


def _render_todos_document(todos: list) -> str:
    """Render TODO.md with status, timestamps, and priority info."""
    lines = ["# TODO", ""]
    open_todos = [t for t in todos if t.status == "open"]
    done_todos = [t for t in todos if t.status == "completed"]
    if open_todos:
        lines.append("## Open")
        lines.append("")
        for item in open_todos:
            lines.append(f"- [ ] **{item.id}**: {item.text}  ")
            lines.append(f"  *Created: {item.created_at}*")
        lines.append("")
    if done_todos:
        lines.append("## Completed")
        lines.append("")
        for item in done_todos:
            lines.append(f"- [x] **{item.id}**: {item.text}  ")
            lines.append(f"  *Completed: {item.updated_at}*")
        lines.append("")
    return "\n".join(lines)


def _next_id(prefix: str, existing: list[str]) -> str:
    numbers = []
    for value in existing:
        try:
            numbers.append(int(value.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"
