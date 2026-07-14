"""Shared bounded helpers for static framework profile tools."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from maldroid.tools.models import ToolContext


def inventory(
    context: ToolContext,
    case_path: str,
    names: set[str] | None = None,
    suffixes: set[str] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    root = context.read_path(case_path)
    candidates = [root] if root.is_file() else (path for path in root.rglob("*") if path.is_file())
    results: list[dict[str, Any]] = []
    for path in candidates:
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
    candidates = [root] if root.is_file() else (path for path in root.rglob("*") if path.is_file())
    results: list[dict[str, Any]] = []
    total = 0
    for path in candidates:
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        try:
            with path.open("rb") as handle:
                if b"\x00" in handle.read(8192):
                    continue
            with path.open(encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if query in line:
                        total += 1
                        if len(results) < limit:
                            results.append(
                                {
                                    "path": display_path(context, root, case_path, path),
                                    "line": number,
                                    "preview": line.strip()[:1000],
                                }
                            )
        except OSError:
            continue
    return {
        "query": query,
        "total_matches": total,
        "returned_matches": len(results),
        "truncated": total > len(results),
        "results": results,
    }


def bounded_read(
    context: ToolContext, case_path: str, start_line: int, end_line: int
) -> dict[str, Any]:
    maximum = context.config.limits.max_read_lines
    if end_line < start_line or end_line - start_line + 1 > maximum:
        raise ValueError(f"Read range must be ordered and no larger than {maximum} lines.")
    path = context.read_path(case_path)
    lines: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            if number > end_line:
                break
            if number >= start_line:
                lines.append({"line": number, "text": line.rstrip()})
    return {"path": case_path, "lines": lines, "returned_lines": len(lines)}


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
    error_text = error.read_text(encoding="utf-8", errors="replace")[:4000]
    if completed.returncode:
        raise ValueError(f"{executable_name} exited with {completed.returncode}: {error_text}")
    preview = output.read_text(encoding="utf-8", errors="replace")[:8000]
    return {
        "command": [executable_name, *arguments],
        "exit_status": completed.returncode,
        "output_file": output.relative_to(context.case.root).as_posix(),
        "stderr_file": error.relative_to(context.case.root).as_posix(),
        "preview": preview,
        "truncated": output.stat().st_size > len(preview.encode("utf-8")),
    }


def display_path(context: ToolContext, root: Path, original: str, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.case.root).as_posix()
    except ValueError:
        if root.is_file():
            return original
        return f"{original.rstrip('/')}/{path.relative_to(root).as_posix()}"
