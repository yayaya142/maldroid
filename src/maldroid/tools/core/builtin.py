"""Small, deterministic core tool set exposed in every profile."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maldroid.evidence_manager import EvidenceManager
from maldroid.io_utils import read_text_prefix, read_text_range_bounded, search_text_file_lines
from maldroid.knowledge_manager import KnowledgeManager
from maldroid.large_files import LargeTextIndexer
from maldroid.models import EvidenceReference
from maldroid.paths import DEFAULT_SCAN_IGNORED_DIRECTORIES, walk_regular_entries
from maldroid.profile_detection import detect_profiles
from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFilesInput(Arguments):
    path: str = "."
    max_depth: int = Field(default=4, ge=0, le=20)


class PathInput(Arguments):
    path: str


class FileInfoInput(PathInput):
    calculate_hashes: bool = False


class ReadRangeInput(PathInput):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> ReadRangeInput:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class SearchInput(Arguments):
    query: str = Field(min_length=1, max_length=1000)
    path: str = "."
    case_sensitive: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class RegexSearchInput(SearchInput):
    pass


class ExtractStringsInput(PathInput):
    minimum_length: int = Field(default=6, ge=3, le=256)


class RegisterEvidenceInput(PathInput):
    mode: Literal["symlink", "copy"] = "symlink"
    calculate_hash: bool = False


class DetectProfileInput(Arguments):
    path: str = "."


class SelectProfileInput(Arguments):
    profile: Literal["generic", "react-native", "native", "flutter", "unity", "cordova", "cocos"]
    confidence: Literal["low", "medium", "high"]
    reason: str = Field(min_length=10, max_length=2000)


class SaveNoteInput(Arguments):
    text: str = Field(min_length=1, max_length=50000)
    kind: Literal["research_note", "decision", "hypothesis"] = "research_note"
    title: str | None = Field(default=None, min_length=1, max_length=300)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class SaveCheckpointInput(Arguments):
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


class ListRecordsInput(Arguments):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class GetRecordInput(Arguments):
    record_id: str = Field(min_length=1, max_length=100)


class SaveFindingInput(Arguments):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=20000)
    confidence: Literal["low", "medium", "high"] = "medium"
    severity: Literal["informational", "low", "medium", "high", "critical"] = "medium"
    status: Literal["tentative", "confirmed", "rejected", "resolved"] = "tentative"
    evidence: list[EvidenceReference] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class UpdateFindingInput(Arguments):
    finding_id: str
    changes: dict[str, Any]


class UpdateTodoInput(Arguments):
    action: Literal["add", "complete", "reopen", "remove"]
    text_or_id: str


class KnowledgeSearchInput(Arguments):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=25)


class KnowledgeReadInput(Arguments):
    document_key: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class LargeIndexInput(PathInput):
    chunk_lines: int = Field(default=200, ge=10, le=2000)


class LargeSearchInput(Arguments):
    path: str
    query: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class LargeChunkInput(Arguments):
    path: str
    chunk_number: int = Field(ge=1)


def list_case_files(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ListFilesInput.model_validate(arguments)
    root = context.read_path(values.path)
    ignored = {".git", "__pycache__", ".venv", "cache", "indexes"}
    maximum = context.config.limits.max_file_tree_entries
    entries: list[dict[str, Any]] = []
    base_depth = len(root.parts)
    if root.is_file():
        return {
            "entries": [{"path": values.path, "type": "file", "size": root.stat().st_size}],
            "truncated": False,
        }
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.parts) - base_depth
        directories[:] = [
            item for item in directories if item not in ignored and depth < values.max_depth
        ]
        for name in sorted(directories + files):
            candidate = current_path / name
            relative = _case_display_path(context, root, values.path, candidate)
            is_symlink = candidate.is_symlink()
            entries.append(
                {
                    "path": relative,
                    "type": "symlink"
                    if is_symlink
                    else "directory"
                    if candidate.is_dir()
                    else "file",
                    "size": (
                        candidate.stat().st_size if not is_symlink and candidate.is_file() else None
                    ),
                }
            )
            if len(entries) >= maximum:
                return {"entries": entries, "truncated": True, "limit": maximum}
    return {"entries": entries, "truncated": False}


def get_file_info(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = FileInfoInput.model_validate(arguments)
    path = context.read_path(values.path)
    stat = path.stat()
    result: dict[str, Any] = {
        "path": values.path,
        "type": "directory" if path.is_dir() else "file",
        "mime_type": mimetypes.guess_type(path.name)[0],
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime)
        .astimezone()
        .isoformat(timespec="seconds"),
        "binary": _is_binary(path) if path.is_file() else False,
    }
    if path.is_file() and not result["binary"]:
        result["line_count"] = _count_lines(path)
    if values.calculate_hashes and path.is_file():
        result["sha256"] = _hash(path, "sha256")
    return result


def read_file_range(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReadRangeInput.model_validate(arguments)
    maximum = context.config.limits.max_read_lines
    if values.end_line - values.start_line + 1 > maximum:
        raise ValueError(f"A maximum of {maximum} lines may be read at once.")
    path = context.read_path(values.path)
    if not path.is_file() or _is_binary(path):
        raise ValueError("read_file_range requires a text file.")
    deadline = time.monotonic() + context.config.limits.command_timeout_seconds
    lines, content_truncated, content_budget_exhausted = read_text_range_bounded(
        path,
        values.start_line,
        values.end_line,
        context.config.limits.max_tool_output_characters,
        deadline=deadline,
    )
    return {
        "path": values.path,
        "start_line": values.start_line,
        "end_line": values.end_line,
        "returned_lines": len(lines),
        "content_truncated": content_truncated,
        "range_complete": not content_budget_exhausted,
        "lines": lines,
    }


def search_text(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchInput.model_validate(arguments)
    target = context.read_path(values.path)
    hard_limit = context.config.limits.max_search_results
    if shutil.which("rg"):
        command = _base_rg_command(context, target) + ["--fixed-strings"]
        if not values.case_sensitive:
            command.append("--ignore-case")
        command.extend(["--", values.query, str(target)])
        matches, total_exact = _run_rg(context, command, target, values.path, hard_limit)
    else:
        matches, total_exact = _python_exact_search(
            context,
            target,
            values.path,
            values.query,
            values.case_sensitive,
            hard_limit,
        )
    return _paginate(
        matches,
        values.page,
        values.page_size,
        hard_limit,
        total_exact=total_exact,
    )


def search_regex(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = RegexSearchInput.model_validate(arguments)
    if not shutil.which("rg"):
        raise ValueError("search_regex requires ripgrep so execution can be time-limited safely.")
    try:
        re.compile(values.query)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}") from exc
    target = context.read_path(values.path)
    hard_limit = context.config.limits.max_search_results
    command = _base_rg_command(context, target)
    if not values.case_sensitive:
        command.append("--ignore-case")
    command.extend(["--", values.query, str(target)])
    matches, total_exact = _run_rg(context, command, target, values.path, hard_limit)
    return _paginate(
        matches,
        values.page,
        values.page_size,
        hard_limit,
        total_exact=total_exact,
    )


def count_lines(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = PathInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file():
        raise ValueError("count_lines requires a file.")
    return {"path": values.path, "line_count": _count_lines(path)}


def extract_strings(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ExtractStringsInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file():
        raise ValueError("extract_strings requires a file.")
    output = context.output_directory() / f"strings-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    executable = shutil.which("strings")
    if executable:
        with output.open("wb") as handle:
            completed = subprocess.run(
                [executable, "-n", str(values.minimum_length), str(path)],
                stdout=handle,
                stderr=subprocess.PIPE,
                timeout=context.config.limits.command_timeout_seconds,
                check=False,
            )
        if completed.returncode:
            raise ValueError(completed.stderr.decode("utf-8", errors="replace")[:2000])
    else:
        pattern = re.compile(rb"[ -~]{%d,}" % values.minimum_length)
        with path.open("rb") as source, output.open("wb") as target:
            carry = b""
            for block in iter(lambda: source.read(1024 * 1024), b""):
                data = carry + block
                for match in pattern.finditer(data[: -values.minimum_length] or data):
                    target.write(match.group(0) + b"\n")
                carry = data[-values.minimum_length :]
    preview, truncated = read_text_prefix(output, 4000)
    return {
        "path": values.path,
        "output_file": output.relative_to(context.case.root).as_posix(),
        "preview": preview,
        "truncated": truncated,
    }


def register_evidence(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = RegisterEvidenceInput.model_validate(arguments)
    source = context.read_path(values.path)
    manager = EvidenceManager(context.case_manager)
    record = manager.register(context.case, source, values.mode, values.calculate_hash)
    context.path_policy.evidence_sources[record.case_path] = record.source_resolved_path
    return record.model_dump()


def read_case_state(context: ToolContext, _: BaseModel) -> dict[str, Any]:
    state = context.case.state
    open_todos = [item.model_dump() for item in state.todos if item.status == "open"]
    return {
        "schema_version": state.schema_version,
        "active_profile": state.active_profile,
        "summary": state.summary,
        "counts": {
            "findings": len(state.findings),
            "open_todos": len(open_todos),
            "completed_todos": sum(item.status == "completed" for item in state.todos),
            "research_notes": len(state.notes),
            "checkpoints": len(state.checkpoints),
        },
        "findings": [item.model_dump() for item in state.findings[-20:]],
        "open_todos": open_todos,
        "latest_checkpoint": state.checkpoints[-1].model_dump() if state.checkpoints else None,
        "recent_research_notes": [item.model_dump() for item in state.notes[-5:]],
        "readback": {
            "complete": False,
            "hint": "Use list/get state tools for complete paginated histories.",
        },
    }


def detect_case_profile(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = DetectProfileInput.model_validate(arguments)
    root = context.read_path(values.path)
    registered = [Path(item.source_resolved_path) for item in context.case.state.evidence]
    return detect_profiles(root, registered).as_dict()


def select_case_profile(_: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SelectProfileInput.model_validate(arguments)
    return {
        "selected_profile": values.profile,
        "confidence": values.confidence,
        "reason": values.reason,
        "application": "The MalDroid agent controller applies this validated recommendation.",
    }


def save_note(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SaveNoteInput.model_validate(arguments)
    return context.investigation.save_note(
        context.case,
        values.text,
        values.evidence,
        kind=values.kind,
        title=values.title,
    ).model_dump()


def save_checkpoint(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SaveCheckpointInput.model_validate(arguments)
    return context.investigation.save_checkpoint(
        context.case,
        **values.model_dump(),
    ).model_dump()


def _record_page(records: list[Any], values: ListRecordsInput) -> dict[str, Any]:
    start = (values.page - 1) * values.page_size
    selected = records[start : start + values.page_size]
    return {
        "page": values.page,
        "page_size": values.page_size,
        "total": len(records),
        "truncated": start + len(selected) < len(records),
        "records": [item.model_dump() for item in selected],
    }


def list_findings(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    return _record_page(context.case.state.findings, ListRecordsInput.model_validate(arguments))


def list_notes(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    return _record_page(context.case.state.notes, ListRecordsInput.model_validate(arguments))


def list_todos(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    return _record_page(context.case.state.todos, ListRecordsInput.model_validate(arguments))


def list_checkpoints(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    return _record_page(context.case.state.checkpoints, ListRecordsInput.model_validate(arguments))


def _get_record(records: list[Any], record_id: str, label: str) -> dict[str, Any]:
    item = next((value for value in records if value.id == record_id), None)
    if item is None:
        raise ValueError(f"{label} not found: {record_id}")
    return item.model_dump()


def get_finding(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = GetRecordInput.model_validate(arguments)
    return _get_record(context.case.state.findings, values.record_id, "Finding")


def get_note(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = GetRecordInput.model_validate(arguments)
    return _get_record(context.case.state.notes, values.record_id, "Note")


def get_checkpoint(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = GetRecordInput.model_validate(arguments)
    return _get_record(context.case.state.checkpoints, values.record_id, "Checkpoint")


def save_finding(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SaveFindingInput.model_validate(arguments)
    return context.investigation.save_finding(
        context.case,
        values.title,
        values.summary,
        values.confidence,
        values.severity,
        values.status,
        values.evidence,
        values.tags,
    ).model_dump()


def update_finding(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = UpdateFindingInput.model_validate(arguments)
    return context.investigation.update_finding(
        context.case, values.finding_id, values.changes
    ).model_dump()


def update_todo(context: ToolContext, arguments: BaseModel) -> dict[str, Any] | None:
    values = UpdateTodoInput.model_validate(arguments)
    result = context.investigation.update_todo(context.case, values.action, values.text_or_id)
    return result.model_dump() if result else None


def search_knowledge(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = KnowledgeSearchInput.model_validate(arguments)
    manager = KnowledgeManager(context.case)
    if not manager.list_documents():
        manager.reindex()
    return {
        "results": manager.search(values.query, context.case.state.active_profile, values.limit)
    }


def read_knowledge_range(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = KnowledgeReadInput.model_validate(arguments)
    if values.end_line - values.start_line + 1 > context.config.limits.max_read_lines:
        raise ValueError("Requested knowledge range exceeds the configured read limit.")
    return KnowledgeManager(context.case).read_range(
        values.document_key, values.start_line, values.end_line
    )


def index_large_text_file(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = LargeIndexInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file() or _is_binary(path):
        raise ValueError("Large-text indexing requires a text file.")
    return LargeTextIndexer(context.case.root).index(path, values.path, values.chunk_lines)


def search_large_text_index(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = LargeSearchInput.model_validate(arguments)
    return LargeTextIndexer(context.case.root).search(
        values.path, values.query, values.page, values.page_size
    )


def read_large_text_chunk(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = LargeChunkInput.model_validate(arguments)
    return LargeTextIndexer(context.case.root).read_chunk(
        values.path, values.chunk_number, context.config.limits.max_tool_output_characters
    )


def register_core_tools(registry: ToolRegistry) -> None:
    definitions: list[tuple[str, str, type[BaseModel], ToolHandler]] = [
        ("list_case_files", "List a bounded case file tree.", ListFilesInput, list_case_files),
        (
            "get_file_info",
            "Inspect file metadata without reading its contents.",
            FileInfoInput,
            get_file_info,
        ),
        (
            "read_file_range",
            "Read a bounded line range from a case text file.",
            ReadRangeInput,
            read_file_range,
        ),
        (
            "search_text",
            "Search exact text in case files with bounded results.",
            SearchInput,
            search_text,
        ),
        (
            "search_regex",
            "Run a bounded regular-expression search with ripgrep.",
            RegexSearchInput,
            search_regex,
        ),
        (
            "count_lines",
            "Count file lines without loading the file into memory.",
            PathInput,
            count_lines,
        ),
        (
            "extract_strings",
            "Extract printable strings and save the complete output.",
            ExtractStringsInput,
            extract_strings,
        ),
        (
            "register_evidence",
            "Register an existing case file as evidence.",
            RegisterEvidenceInput,
            register_evidence,
        ),
        (
            "detect_profile",
            "Detect the best analysis profile from bounded artifact indicators.",
            DetectProfileInput,
            detect_case_profile,
        ),
        (
            "select_profile",
            "Select an analysis profile after inspecting concrete artifact evidence.",
            SelectProfileInput,
            select_case_profile,
        ),
        (
            "read_case_state",
            "Read the compact persistent investigation state.",
            Arguments,
            read_case_state,
        ),
        (
            "save_note",
            "Save a meaningful research note, decision, or hypothesis; never log tool activity.",
            SaveNoteInput,
            save_note,
        ),
        (
            "save_checkpoint",
            "Save typed research continuity with learned evidence and an exact next action.",
            SaveCheckpointInput,
            save_checkpoint,
        ),
        (
            "list_findings",
            "List complete findings with pagination.",
            ListRecordsInput,
            list_findings,
        ),
        ("get_finding", "Read one finding by stable ID.", GetRecordInput, get_finding),
        (
            "list_notes",
            "List meaningful research notes with pagination.",
            ListRecordsInput,
            list_notes,
        ),
        ("get_note", "Read one research note by stable ID.", GetRecordInput, get_note),
        (
            "list_todos",
            "List open and completed TODOs with pagination.",
            ListRecordsInput,
            list_todos,
        ),
        (
            "list_checkpoints",
            "List typed research checkpoints with pagination.",
            ListRecordsInput,
            list_checkpoints,
        ),
        (
            "get_checkpoint",
            "Read one typed research checkpoint by stable ID.",
            GetRecordInput,
            get_checkpoint,
        ),
        (
            "save_finding",
            "Save a structured evidence-backed finding.",
            SaveFindingInput,
            save_finding,
        ),
        (
            "update_finding",
            "Update an existing structured finding.",
            UpdateFindingInput,
            update_finding,
        ),
        (
            "update_todo",
            "Add, complete, reopen, or remove an investigation TODO.",
            UpdateTodoInput,
            update_todo,
        ),
        (
            "search_knowledge",
            "Search bounded local research playbooks.",
            KnowledgeSearchInput,
            search_knowledge,
        ),
        (
            "read_knowledge_range",
            "Read a bounded range from a knowledge document.",
            KnowledgeReadInput,
            read_knowledge_range,
        ),
        (
            "index_large_text_file",
            "Build a contentless chunk index for a large text file.",
            LargeIndexInput,
            index_large_text_file,
        ),
        (
            "search_large_text_index",
            "Search indexed large-text chunks.",
            LargeSearchInput,
            search_large_text_index,
        ),
        (
            "read_large_text_chunk",
            "Read one bounded chunk from an indexed source.",
            LargeChunkInput,
            read_large_text_chunk,
        ),
    ]
    for name, description, model, handler in definitions:
        registry.register(ToolDefinition(name, "core", description, model, handler))


def _is_binary(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        sample = handle.read(8192)
    return b"\x00" in sample


def _count_lines(path: Path) -> int:
    count = 0
    last = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            count += block.count(b"\n")
            last = block[-1:]
    if path.stat().st_size and last != b"\n":
        count += 1
    return count


def _hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _base_rg_command(context: ToolContext, target: Path) -> list[str]:
    command = [
        "rg",
        "--line-number",
        "--with-filename",
        "--null",
        "--color",
        "never",
        "--max-columns",
        "2000",
        "--max-columns-preview",
    ]
    try:
        target_parts = target.relative_to(context.case.root.resolve()).parts
    except ValueError:
        target_parts = ()
    for directory in sorted(DEFAULT_SCAN_IGNORED_DIRECTORIES):
        if directory in target_parts:
            continue
        command.extend(["--glob", f"!{directory}/**", "--glob", f"!**/{directory}/**"])
    return command


def _run_rg(
    context: ToolContext,
    command: list[str],
    target: Path,
    display: str,
    hard_limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    matches: list[dict[str, Any]] = []
    stopped_early = False
    timed_out = threading.Event()
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=stderr,
            cwd=context.case.root,
        )

        def stop_on_timeout() -> None:
            if process.poll() is not None:
                return
            timed_out.set()
            with suppress(OSError):
                process.kill()

        timer = threading.Timer(context.config.limits.command_timeout_seconds, stop_on_timeout)
        timer.daemon = True
        timer.start()
        try:
            assert process.stdout is not None
            pending_path = b""
            with process.stdout:
                for raw_line in process.stdout:
                    pending_path += raw_line
                    raw_path, separator, remainder = pending_path.partition(b"\x00")
                    if not separator:
                        # POSIX filenames may contain newlines. Ripgrep's NUL separator is the
                        # authoritative path boundary, so retain partial path records until it.
                        continue
                    pending_path = b""
                    raw_number, colon, raw_preview = remainder.partition(b":")
                    if not colon:
                        continue
                    try:
                        line_number = int(raw_number)
                    except ValueError:
                        continue
                    found_path = Path(raw_path.decode(errors="replace"))
                    matches.append(
                        {
                            "path": _case_display_path(context, target, display, found_path),
                            "line": line_number,
                            "preview": raw_preview.decode("utf-8", errors="replace").rstrip("\r\n")[
                                :1000
                            ],
                        }
                    )
                    if len(matches) > hard_limit:
                        stopped_early = True
                        timer.cancel()
                        with suppress(OSError):
                            process.terminate()
                        break
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait()
        finally:
            timer.cancel()
        stderr.seek(0)
        error_text = stderr.read(2000).decode("utf-8", errors="replace")
    if timed_out.is_set():
        raise ValueError(
            f"ripgrep exceeded the {context.config.limits.command_timeout_seconds}-second limit"
        )
    if not stopped_early and returncode not in {0, 1}:
        raise ValueError(error_text or f"ripgrep exited with {returncode}")
    return matches, not stopped_early


def _python_exact_search(
    context: ToolContext,
    target: Path,
    display: str,
    query: str,
    case_sensitive: bool,
    hard_limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    needle = query if case_sensitive else query.lower()
    results: list[dict[str, Any]] = []
    deadline = time.monotonic() + context.config.limits.command_timeout_seconds
    for path in walk_regular_entries(target):
        if time.monotonic() >= deadline:
            return results, False
        try:
            _, file_matches, complete = search_text_file_lines(
                path,
                needle,
                case_sensitive=case_sensitive,
                max_results=hard_limit + 1 - len(results),
                stop_after=hard_limit + 1 - len(results),
                deadline=deadline,
            )
            relative = (
                display
                if target.is_file()
                else f"{display.rstrip('/')}/{path.relative_to(target).as_posix()}"
            )
            results.extend(
                {"path": relative, "line": number, "preview": preview}
                for number, preview in file_matches
            )
            if not complete or len(results) > hard_limit:
                return results, False
        except OSError:
            continue
    return results, True


def _paginate(
    matches: list[dict[str, Any]],
    page: int,
    page_size: int,
    hard_limit: int,
    *,
    total_exact: bool = True,
) -> dict[str, Any]:
    limited = matches[:hard_limit]
    start = (page - 1) * page_size
    results = limited[start : start + page_size]
    return {
        "total_matches": len(matches),
        "total_matches_exact": total_exact,
        "bounded_matches": len(limited),
        "returned_matches": len(results),
        "page": page,
        "truncated": (
            not total_exact or len(matches) > hard_limit or start + len(results) < len(limited)
        ),
        "results": results,
    }


def _case_display_path(context: ToolContext, root: Path, display: str, candidate: Path) -> str:
    candidate = candidate.absolute()
    try:
        return candidate.relative_to(context.case.root).as_posix()
    except ValueError:
        if root.is_file():
            return display
        try:
            suffix = candidate.relative_to(root).as_posix()
            return f"{display.rstrip('/')}/{suffix}" if suffix != "." else display
        except ValueError:
            return display
