"""Append-only session history and durable summaries."""

from __future__ import annotations

import re
from typing import Any

from maldroid.case_manager import Case, CaseManager
from maldroid.io_utils import append_jsonl, atomic_write_text
from maldroid.models import SessionEvent


class SessionManager:
    def __init__(self, case: Case, case_manager: CaseManager):
        self.case = case
        self.case_manager = case_manager
        directory = case.internal / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        numbers = []
        for path in directory.glob("session-*.jsonl"):
            match = re.match(r"session-(\d+)\.jsonl", path.name)
            if match:
                numbers.append(int(match.group(1)))
        self.number = max(numbers, default=0) + 1
        self.history_path = directory / f"session-{self.number:04d}.jsonl"
        self.summary_path = directory / f"session-{self.number:04d}-summary.md"
        case.state.sessions.append(self.history_path.relative_to(case.root).as_posix())
        case_manager.save(case)

    def record(
        self, event_type: str, role: str | None = None, content: Any = None, **extra: Any
    ) -> None:
        event = SessionEvent(type=event_type, role=role, content=content, **extra)
        append_jsonl(self.history_path, event.model_dump(mode="json"))

    def save_summary(self, summary: str) -> None:
        atomic_write_text(self.summary_path, "# Session Summary\n\n" + summary.strip() + "\n")
        self.case.state.summary = summary.strip()
        self.case_manager.save(self.case)
        notes_summary = self.case.root / "notes" / "SESSION_SUMMARY.md"
        notes_summary.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(notes_summary, "# Session Summary\n\n" + summary.strip() + "\n")

    @staticmethod
    def load_latest_summary(case: Case) -> str:
        directory = case.internal / "sessions"
        summaries = sorted(directory.glob("session-*-summary.md")) if directory.exists() else []
        if not summaries:
            return case.state.summary
        text = summaries[-1].read_text(encoding="utf-8", errors="replace")
        return text.split("\n", 2)[-1].strip()
