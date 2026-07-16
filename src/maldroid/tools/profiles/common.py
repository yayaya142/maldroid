"""Shared bounded helpers for static framework profile tools."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from maldroid.io_utils import read_text_prefix, read_text_range_bounded, search_text_file_lines
from maldroid.paths import walk_regular_entries
from maldroid.tools.models import ToolContext


def inventory(
    context: ToolContext,
    case_path: str,
    names: set[str] | None = None,
    suffixes: set[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    root = context.read_path(case_path)
    results: list[dict[str, Any]] = []
    for path in walk_regular_entries(root):
        lower = path.name.lower()
        if names and lower not in names and not (suffixes and path.suffix.lower() in suffixes):
            continue
        if not names and suffixes and path.suffix.lower() not in suffixes:
            continue
        results.append(
            {
                "path": display_path(context, root, case_path, path),
                "name": path.name,
                "size": path.stat().st_size,
            }
        )
        if len(results) >= limit:
            break
    return results


def exact_search(
    context: ToolContext,
    case_path: str,
    query: str,
    suffixes: set[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    root = context.read_path(case_path)
    results: list[dict[str, Any]] = []
    total = 0
    complete = True
    deadline = time.monotonic() + context.config.limits.command_timeout_seconds
    for path in walk_regular_entries(root):
        if time.monotonic() >= deadline:
            complete = False
            break
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        try:
            with path.open("rb") as handle:
                if b"\x00" in handle.read(8192):
                    continue
            found, file_matches, file_complete = search_text_file_lines(
                path,
                query,
                case_sensitive=True,
                max_results=max(0, limit - len(results)),
                deadline=deadline,
            )
            total += found
            results.extend(
                {
                    "path": display_path(context, root, case_path, path),
                    "line": number,
                    "preview": preview,
                }
                for number, preview in file_matches
            )
            if not file_complete:
                complete = False
                break
        except OSError:
            continue
    return {
        "query": query,
        "total_matches": total,
        "returned_matches": len(results),
        "truncated": not complete or total > len(results),
        "scan_complete": complete,
        "results": results,
    }


def bounded_read(
    context: ToolContext, case_path: str, start_line: int, end_line: int
) -> dict[str, Any]:
    maximum = context.config.limits.max_read_lines
    if end_line < start_line or end_line - start_line + 1 > maximum:
        raise ValueError(f"Read range must be ordered and no larger than {maximum} lines.")
    path = context.read_path(case_path)
    deadline = time.monotonic() + context.config.limits.command_timeout_seconds
    lines, content_truncated, content_budget_exhausted = read_text_range_bounded(
        path,
        start_line,
        end_line,
        context.config.limits.max_tool_output_characters,
        deadline=deadline,
    )
    return {
        "path": case_path,
        "lines": lines,
        "returned_lines": len(lines),
        "content_truncated": content_truncated,
        "range_complete": not content_budget_exhausted,
    }


def run_allowlisted(
    context: ToolContext,
    executable_name: str,
    arguments: list[str],
    output_stem: str,
) -> dict[str, Any]:
    executable = shutil.which(executable_name)
    if not executable:
        raise ValueError(f"Required static tool is not available: {executable_name}")
    output = (
        context.output_directory() / f"{output_stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    )
    error = output.with_suffix(".stderr.txt")
    with output.open("wb") as stdout, error.open("wb") as stderr:
        completed = subprocess.run(
            [executable, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=context.case.root,
            timeout=context.config.limits.command_timeout_seconds,
            check=False,
        )
    error_text, _ = read_text_prefix(error, 4000)
    if completed.returncode:
        raise ValueError(f"{executable_name} exited with {completed.returncode}: {error_text}")
    preview, truncated = read_text_prefix(output, 8000)
    return {
        "command": [executable_name, *arguments],
        "exit_status": completed.returncode,
        "output_file": output.relative_to(context.case.root).as_posix(),
        "stderr_file": error.relative_to(context.case.root).as_posix(),
        "preview": preview,
        "truncated": truncated,
    }


def display_path(context: ToolContext, root: Path, original: str, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.case.root).as_posix()
    except ValueError:
        if root.is_file():
            return original
        return f"{original.rstrip('/')}/{path.relative_to(root).as_posix()}"
