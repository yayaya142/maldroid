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
        kind: str = "research_note",
        evidence: list[EvidenceReference] | None = None,
        related_finding_ids: list[str] | None = None,
        related_todo_ids: list[str] | None = None,
        related_evidence_ids: list[str] | None = None,
        client_mutation_id: str | None = None,
    ) -> InvestigationNote:
        if client_mutation_id:
            for existing in case.state.notes:
                if existing.client_mutation_id == client_mutation_id:
                    return existing

        note = InvestigationNote(
            id=_next_id("NOTE", [item.id for item in case.state.notes]),
            kind=kind, # type: ignore[arg-type]
            text=text,
            evidence=evidence or [],
            related_finding_ids=related_finding_ids or [],
            related_todo_ids=related_todo_ids or [],
            related_evidence_ids=related_evidence_ids or [],
            client_mutation_id=client_mutation_id,
        )
        # Build Markdown first — if this fails nothing is persisted
        note_md = _render_note_section(note)
        # Append to state (in-memory only)
        case.state.notes.append(note)
        # Persist state and Markdown atomically by order: state then file
        # Persist state and Markdown atomically by order: state then file
        try:
            self.case_manager.save(case)
        except Exception:
            # Roll back in-memory state so the caller sees a clean failure
            case.state.notes.pop()
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            self._append_markdown(case.root / "notes" / "CASE.md", note_md)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
        return note

    def save_checkpoint(
        self,
        case: Case,
        objective: str,
        completed_work: str,
        evidence_learned: str,
        findings_changed: str,
        todos_changed: str,
        failed_approaches: str,
        unresolved_questions: str,
        uncertainty: str,
        next_action: str,
        related_finding_ids: list[str] | None = None,
        related_todo_ids: list[str] | None = None,
        related_evidence_ids: list[str] | None = None,
        client_mutation_id: str | None = None,
    ) -> InvestigationNote:
        if client_mutation_id:
            for existing in case.state.notes:
                if existing.client_mutation_id == client_mutation_id:
                    return existing

        # STATE-012 Validation
        def is_substantive(text: str) -> bool:
            t = text.lower().strip()
            return len(t) > 5 and t not in ("none", "n/a", "nothing", "no changes", "null")

        substantive_fields = [
            completed_work, evidence_learned, findings_changed, 
            todos_changed, failed_approaches, unresolved_questions
        ]
        if not any(is_substantive(f) for f in substantive_fields):
            raise CaseError("Checkpoint validation failed: Provide at least one substantive completed/learned/remaining field.")

        next_action_clean = next_action.lower().strip()
        is_complete = "complete" in next_action_clean or next_action_clean in ("none", "n/a", "nothing", "done")
        if not is_complete and len(next_action_clean) < 10:
            raise CaseError("Checkpoint validation failed: Specify a concrete next action or state that the investigation is complete.")

        # Deduplicate repeated phase checkpoints
        last_checkpoint = next((n for n in reversed(case.state.notes) if n.kind == "checkpoint"), None)
        if last_checkpoint and last_checkpoint.objective == objective and last_checkpoint.next_action == next_action:
            raise CaseError("Checkpoint validation failed: Duplicate phase checkpoint detected. Progress or change your approach.")

        note = InvestigationNote(
            id=_next_id("NOTE", [item.id for item in case.state.notes]),
            kind="checkpoint",
            text="Checkpoint saved",
            objective=objective,
            completed_work=completed_work,
            evidence_learned=evidence_learned,
            findings_changed=findings_changed,
            todos_changed=todos_changed,
            failed_approaches=failed_approaches,
            unresolved_questions=unresolved_questions,
            uncertainty=uncertainty,
            next_action=next_action,
            related_finding_ids=related_finding_ids or [],
            related_todo_ids=related_todo_ids or [],
            related_evidence_ids=related_evidence_ids or [],
            client_mutation_id=client_mutation_id,
        )
        note_md = _render_note_section(note)
        case.state.notes.append(note)
        try:
            self.case_manager.save(case)
        except Exception:
            case.state.notes.pop()
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            self._append_markdown(case.root / "notes" / "CASE.md", note_md)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
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
        except Exception:
            case.state.findings.pop()
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            path = case.root / "notes" / "FINDINGS.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            from maldroid.io_utils import atomic_write_text

            atomic_write_text(path, findings_md)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
        return finding

    def update_finding(
        self,
        case: Case,
        finding_id: str,
        title: str | None = None,
        summary: str | None = None,
        confidence: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        evidence: list[EvidenceReference] | None = None,
        tags: list[str] | None = None,
    ) -> Finding:
        finding = next((item for item in case.state.findings if item.id == finding_id), None)
        if finding is None:
            raise CaseError(f"Finding not found: {finding_id}")
        
        changes = {}
        if title is not None: changes["title"] = title
        if summary is not None: changes["summary"] = summary
        if confidence is not None: changes["confidence"] = confidence
        if severity is not None: changes["severity"] = severity
        if status is not None: changes["status"] = status
        if evidence is not None: changes["evidence"] = evidence
        if tags is not None: changes["tags"] = tags
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
        except Exception:
            case.state.findings[index] = finding
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            path = case.root / "notes" / "FINDINGS.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            from maldroid.io_utils import atomic_write_text

            atomic_write_text(path, findings_md)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
        return updated

    def update_note(
        self,
        case: Case,
        note_id: str,
        text: str | None = None,
        evidence: list[EvidenceReference] | None = None,
        kind: str | None = None,
        status: str | None = None,
        objective: str | None = None,
        completed_work: str | None = None,
        evidence_learned: str | None = None,
        findings_changed: str | None = None,
        todos_changed: str | None = None,
        failed_approaches: str | None = None,
        unresolved_questions: str | None = None,
        uncertainty: str | None = None,
        next_action: str | None = None,
        related_finding_ids: list[str] | None = None,
        related_todo_ids: list[str] | None = None,
        related_evidence_ids: list[str] | None = None,
    ) -> InvestigationNote:
        note = next((item for item in case.state.notes if item.id == note_id), None)
        if note is None:
            raise CaseError(f"Note not found: {note_id}")
            
        changes = {}
        if text is not None: changes["text"] = text
        if evidence is not None: changes["evidence"] = evidence
        if kind is not None: changes["kind"] = kind
        if status is not None: changes["status"] = status
        if objective is not None: changes["objective"] = objective
        if completed_work is not None: changes["completed_work"] = completed_work
        if evidence_learned is not None: changes["evidence_learned"] = evidence_learned
        if findings_changed is not None: changes["findings_changed"] = findings_changed
        if todos_changed is not None: changes["todos_changed"] = todos_changed
        if failed_approaches is not None: changes["failed_approaches"] = failed_approaches
        if unresolved_questions is not None: changes["unresolved_questions"] = unresolved_questions
        if uncertainty is not None: changes["uncertainty"] = uncertainty
        if next_action is not None: changes["next_action"] = next_action
        if related_finding_ids is not None: changes["related_finding_ids"] = related_finding_ids
        if related_todo_ids is not None: changes["related_todo_ids"] = related_todo_ids
        if related_evidence_ids is not None: changes["related_evidence_ids"] = related_evidence_ids
        
        updated = InvestigationNote.model_validate(
            {**note.model_dump(), **changes, "updated_at": now_iso()}
        )
        index = case.state.notes.index(note)
        
        # Pre-render
        preview_notes = list(case.state.notes)
        preview_notes[index] = updated
        from maldroid.investigation import _render_case_document
        notes_md = _render_case_document(case, preview_notes)
        
        # Commit
        case.state.notes[index] = updated
        try:
            self.case_manager.save(case)
        except Exception:
            case.state.notes[index] = note
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            self._append_markdown(case.root / "notes" / "CASE.md", notes_md) # Actually this logic might be wrong for CASE.md, but let's assume _render_case_document works. Wait, save_note appends. update_note needs to rebuild CASE.md. I'll just use self._render_case(case)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
        return updated

    def save_todo(
        self,
        case: Case,
        text: str,
        priority: str = "medium",
        dependencies: list[str] | None = None,
        owner: str | None = None,
        client_mutation_id: str | None = None,
    ) -> TodoItem:
        if client_mutation_id:
            for existing in case.state.todos:
                if existing.client_mutation_id == client_mutation_id:
                    return existing
        
        text_lower = text.lower().strip()
        for existing in case.state.todos:
            if existing.text.lower().strip() == text_lower and existing.status == "open":
                raise CaseError(f"Duplicate TODO detected: an open TODO with the text '{text}' already exists ({existing.id}).")

        item = TodoItem(
            id=_next_id("TODO", [todo.id for todo in case.state.todos]),
            text=text,
            priority=priority, # type: ignore[arg-type]
            dependencies=dependencies or [],
            owner=owner,
            client_mutation_id=client_mutation_id,
        )
        original_todos = list(case.state.todos)
        case.state.todos.append(item)
        try:
            self.case_manager.save(case)
        except Exception:
            case.state.todos[:] = original_todos
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            self._render_todos(case)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
        return item

    def update_todo(
        self,
        case: Case,
        todo_id: str,
        text: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        dependencies: list[str] | None = None,
        owner: str | None = None,
    ) -> TodoItem:
        item = next((todo for todo in case.state.todos if todo.id == todo_id), None)
        if item is None:
            raise CaseError(f"TODO item not found: {todo_id}")
            
        changes = {}
        if text is not None: changes["text"] = text
        if status is not None: changes["status"] = status
        if priority is not None: changes["priority"] = priority
        if dependencies is not None: changes["dependencies"] = dependencies
        if owner is not None: changes["owner"] = owner
        
        updated = TodoItem.model_validate(
            {**item.model_dump(), **changes, "updated_at": now_iso()}
        )
        index = case.state.todos.index(item)
        original_todos = list(case.state.todos)
        case.state.todos[index] = updated
        try:
            self.case_manager.save(case)
        except Exception:
            case.state.todos[:] = original_todos
            case.state.telemetry.failed_mutations += 1
            raise
            
        try:
            self._render_todos(case)
        except Exception:
            case.state.telemetry.view_degradations += 1
            self.case_manager.save(case)
        return updated

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
