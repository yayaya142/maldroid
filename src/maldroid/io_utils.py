"""Atomic local persistence helpers."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, TextIO

from filelock import FileLock


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Atomically replace a text file while serializing concurrent writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    """Serialize JSON deterministically and atomically."""
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, value: Any) -> None:
    """Append one JSON object to an audit stream under a file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_text_prefix(path: Path, max_characters: int) -> tuple[str, bool]:
    """Read a bounded text prefix without materializing the remainder of a large output file."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        content = handle.read(max_characters)
        truncated = bool(handle.read(1))
    return content, truncated


def read_text_range_bounded(
    path: Path,
    start_line: int,
    end_line: int,
    max_characters: int,
    *,
    deadline: float | None = None,
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Read a logical line range without ever materializing one oversized line."""
    lines: list[dict[str, Any]] = []
    remaining_characters = max_characters
    per_line_limit = min(4000, remaining_characters)
    content_truncated = False
    content_budget_exhausted = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number in range(1, end_line + 1):
            requested = number >= start_line
            capture_limit = min(per_line_limit, remaining_characters) if requested else 0
            if requested and capture_limit <= 0:
                content_truncated = True
                content_budget_exhausted = True
                break
            record = _read_logical_line_prefix(handle, capture_limit, deadline)
            if record is None:
                break
            text, line_truncated = record
            if requested:
                lines.append({"line": number, "text": text, "truncated": line_truncated})
                remaining_characters -= len(text)
                content_truncated = content_truncated or line_truncated
    return lines, content_truncated, content_budget_exhausted


def _read_logical_line_prefix(
    handle: TextIO, capture_limit: int, deadline: float | None
) -> tuple[str, bool] | None:
    captured: list[str] = []
    captured_characters = 0
    line_characters = 0
    received_data = False
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Text range read exceeded the configured command timeout.")
        block = handle.readline(65536)
        if not block:
            break
        received_data = True
        complete = block.endswith("\n")
        content = block[:-1] if complete else block
        if complete and content.endswith("\r"):
            content = content[:-1]
        line_characters += len(content)
        if captured_characters < capture_limit:
            excerpt = content[: capture_limit - captured_characters]
            captured.append(excerpt)
            captured_characters += len(excerpt)
        if complete:
            break
    if not received_data:
        return None
    return "".join(captured), line_characters > capture_limit


def search_text_file_lines(
    path: Path,
    query: str,
    *,
    case_sensitive: bool,
    max_results: int,
    stop_after: int | None = None,
    deadline: float | None = None,
) -> tuple[int, list[tuple[int, str]], bool]:
    """Search logical lines in bounded chunks so a minified line cannot exhaust memory."""
    needle = query if case_sensitive else query.lower()
    search_tail_width = max(1000, len(query) - 1)
    total = 0
    matches: list[tuple[int, str]] = []
    line_number = 1
    line_started = False
    line_matched = False
    search_tail = ""

    def finish_line() -> None:
        nonlocal line_matched
        line_matched = False

    with path.open(encoding="utf-8", errors="replace") as handle:
        while chunk := handle.readline(65536):
            if deadline is not None and time.monotonic() >= deadline:
                return total, matches, False
            line_started = True
            candidate = search_tail + chunk
            if not line_matched:
                searchable = candidate if case_sensitive else candidate.lower()
                match_start = searchable.find(needle)
                if match_start >= 0:
                    line_matched = True
                    total += 1
                    if len(matches) < max_results:
                        preview_start = max(0, match_start - 400)
                        preview_end = min(len(candidate), preview_start + 1000)
                        if preview_end < match_start + len(query):
                            preview_end = min(len(candidate), match_start + len(query))
                            preview_start = max(0, preview_end - 1000)
                        matches.append(
                            (
                                line_number,
                                candidate[preview_start:preview_end].rstrip("\r\n"),
                            )
                        )
                    if stop_after is not None and total >= stop_after:
                        return total, matches, False
            if chunk.endswith("\n"):
                finish_line()
                line_number += 1
                line_started = False
                search_tail = ""
            else:
                search_tail = candidate[-search_tail_width:]
    if line_started:
        finish_line()
    return total, matches, True
