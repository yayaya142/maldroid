"""Bounded source indexing, obfuscation triage, and review-only decoder scripts."""

from __future__ import annotations

import ast
import base64
import binascii
import bz2
import codecs
import difflib
import hashlib
import importlib.metadata
import json
import lzma
import math
import os
import platform
import re
import sqlite3
import sys
import time
import uuid
import zlib
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote_to_bytes

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from maldroid.io_utils import (
    atomic_write_json,
    atomic_write_text,
    read_text_range_bounded,
    search_text_file_lines,
)
from maldroid.models import now_iso
from maldroid.paths import walk_regular_entries
from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry

MIB = 1024 * 1024
CODE_INDEX_PATH = ".maldroid/indexes/source-code.sqlite"
MAX_TRANSFORM_OUTPUT_BYTES = 2 * MIB
MAX_LZMA_MEMORY_BYTES = 64 * MIB
MAX_SCRIPT_SOURCE_CHARACTERS = 256 * 1024
SOURCE_SCAN_OVERLAP = 4096

LANGUAGES: dict[str, str] = {
    ".asm": "Assembly",
    ".c": "C",
    ".cc": "C++",
    ".cjs": "JavaScript",
    ".cpp": "C++",
    ".cs": "C#",
    ".cxx": "C++",
    ".dart": "Dart",
    ".go": "Go",
    ".groovy": "Groovy",
    ".h": "C/C++ header",
    ".hpp": "C++ header",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript JSX",
    ".kt": "Kotlin",
    ".kts": "Kotlin script",
    ".lua": "Lua",
    ".m": "Objective-C",
    ".mjs": "JavaScript",
    ".mm": "Objective-C++",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".s": "Assembly",
    ".scala": "Scala",
    ".smali": "Smali",
    ".sol": "Solidity",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript TSX",
    ".vue": "Vue",
}
SOURCE_SUFFIXES = frozenset(LANGUAGES)

IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?[\"']([^\"']+)[\"']"),
    re.compile(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
    re.compile(r"(?m)^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]"),
    re.compile(r"(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"),
    re.compile(r"(?m)^\s*use\s+([A-Za-z_][\w:]*)"),
    re.compile(r"(?m)^\s*(?:package|using)\s+([A-Za-z_][\w.]*)"),
)

DECLARATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("class", re.compile(r"\b(?:class|interface|object|enum|struct|trait)\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"\b(?:function|fun|def|fn)\s+([A-Za-z_$][\w$]*)\s*[<(]")),
    (
        "function",
        re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\("),
    ),
    ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
    (
        "function",
        re.compile(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        ),
    ),
    ("smali_method", re.compile(r"(?m)^\.method\s+[^\n]*?([A-Za-z_$<>][\w$<>]*)\(")),
    ("smali_class", re.compile(r"(?m)^\.class\s+[^\n]*?L([^;]+);")),
)

SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "network": re.compile(r"\b(?:fetch|axios|XMLHttpRequest|OkHttp|Retrofit|connect|send|recv)\b"),
    "dynamic_code": re.compile(
        r"\b(?:eval|exec|DexClassLoader|PathClassLoader|InMemoryDexClassLoader|dlopen|dlsym|loadLibrary)\b"
    ),
    "encoding": re.compile(
        r"\b(?:atob|btoa|Base64\.decode|fromBase64|decodeURIComponent|fromCharCode)\b"
    ),
    "crypto": re.compile(
        r"\b(?:Cipher|getInstance|SecretKeySpec|CryptoJS|AES|DES|RSA|ChaCha|Salsa20)\b"
    ),
    "native_bridge": re.compile(
        r"\b(?:NativeModules|TurboModule|JNI_OnLoad|RegisterNatives|addJavascriptInterface)\b"
    ),
}

ENCODED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "hex",
        re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){16,}(?![0-9A-Fa-f])"),
    ),
    (
        "base64",
        re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{24,}={0,2}(?![A-Za-z0-9+/_=-])"),
    ),
    ("unicode_escape", re.compile(r"(?:\\u[0-9A-Fa-f]{4}){4,}")),
    ("url", re.compile(r"(?:%[0-9A-Fa-f]{2}){6,}")),
)

DECODE_SIGNAL_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "Base64 decoding",
        "base64 decoder",
        re.compile(r"\b(?:atob|Base64\.decode|base64\.b64decode|Buffer\.from)\b"),
    ),
    (
        "character-code construction",
        "character-code construction",
        re.compile(r"\b(?:String\.fromCharCode|String\.fromCodePoint|chr)\s*\("),
    ),
    (
        "URL decoding",
        "URL decoding",
        re.compile(r"\b(?:decodeURIComponent|decodeURI|unquote(?:_to_bytes)?)\s*\("),
    ),
    (
        "XOR transform",
        "XOR operation",
        re.compile(r"(?:\^|\bxor\b)"),
    ),
    (
        "compression",
        "compression or decompression",
        re.compile(r"\b(?:gzip|gunzip|inflate|deflate|zlib|lzma|bzip2|bz2)\b", re.I),
    ),
    (
        "cryptographic API",
        "cryptographic API",
        re.compile(r"\b(?:Cipher|getInstance|CryptoJS|AES|DES|RSA|ChaCha|Salsa20)\b"),
    ),
)

BLOCKED_IMPORTS: dict[str, str] = {
    "aiohttp": "network access",
    "asyncio.subprocess": "process execution",
    "ctypes": "native code loading",
    "dill": "unsafe object deserialization",
    "ftplib": "network access",
    "http.client": "network access",
    "httpx": "network access",
    "importlib": "dynamic importing",
    "multiprocessing": "child-process creation",
    "paramiko": "network access",
    "pickle": "unsafe object deserialization",
    "requests": "network access",
    "runpy": "dynamic code execution",
    "shelve": "unsafe object deserialization",
    "smtplib": "network access",
    "socket": "network access",
    "subprocess": "process execution",
    "urllib.request": "network access",
    "urllib3": "network access",
    "websocket": "network access",
    "websockets": "network access",
}
BLOCKED_CALLS = {
    "__import__": "dynamic importing",
    "breakpoint": "interactive debugger entry",
    "compile": "dynamic code compilation",
    "eval": "dynamic code execution",
    "exec": "dynamic code execution",
    "os.popen": "process execution",
    "os.spawnl": "process execution",
    "os.spawnle": "process execution",
    "os.spawnlp": "process execution",
    "os.spawnlpe": "process execution",
    "os.spawnv": "process execution",
    "os.spawnve": "process execution",
    "os.spawnvp": "process execution",
    "os.spawnvpe": "process execution",
    "os.system": "process execution",
    "shutil.rmtree": "recursive deletion",
}
BLOCKED_METHODS = {"connect", "rmdir", "unlink"}
WRITE_METHODS = {"open", "write_bytes", "write_text"}
PATH_ARGUMENT_CALLS = {
    "Path",
    "io.open",
    "open",
    "pathlib.Path",
}


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildCodeIndexInput(Arguments):
    path: str = Field(default=".", description="Case-relative source file or tree to index.")
    max_files: int = Field(default=20000, ge=1, le=50000)
    max_entries: int = Field(default=100000, ge=100, le=500000)
    max_file_bytes: int = Field(default=256 * MIB, ge=65536, le=1024 * MIB)
    max_total_bytes: int = Field(default=512 * MIB, ge=65536, le=4 * 1024 * MIB)


class QueryCodeIndexInput(Arguments):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Declaration, import, signal, or filename substring to locate.",
    )
    kind: Literal["any", "file", "declaration", "import", "signal"] = "any"
    path_prefix: str | None = Field(default=None, max_length=4096)
    limit: int = Field(default=50, ge=1, le=500)


class ReadCodeContextInput(Arguments):
    path: str = Field(description="Case-relative decoded source file.")
    symbol: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Exact symbol text to locate; mutually exclusive with line.",
    )
    line: int | None = Field(
        default=None, ge=1, description="Target line; mutually exclusive with symbol."
    )
    occurrence: int = Field(default=1, ge=1, le=100)
    before_lines: int = Field(default=8, ge=0, le=200)
    after_lines: int = Field(default=20, ge=0, le=300)
    max_characters: int = Field(default=30000, ge=1000, le=60000)

    @model_validator(mode="after")
    def require_one_target(self) -> ReadCodeContextInput:
        if (self.symbol is None) == (self.line is None):
            raise ValueError("provide exactly one of symbol or line")
        return self


class AnalyzeObfuscationInput(Arguments):
    path: str = Field(description="Case-relative decoded source file to inspect statically.")
    max_candidates: int = Field(default=50, ge=1, le=500)
    max_signals: int = Field(default=100, ge=1, le=500)
    max_scan_bytes: int = Field(default=128 * MIB, ge=65536, le=1024 * MIB)


TransformOperation = Literal[
    "base64",
    "base32",
    "hex",
    "url",
    "unicode_escape",
    "rot13",
    "reverse",
    "xor",
    "add",
    "subtract",
    "rotate_left",
    "rotate_right",
    "gzip",
    "zlib",
    "bz2",
    "lzma",
]


class TransformStep(Arguments):
    operation: TransformOperation
    key: int | None = Field(default=None, ge=0, le=255)

    @model_validator(mode="after")
    def validate_key(self) -> TransformStep:
        keyed = {"xor", "add", "subtract", "rotate_left", "rotate_right"}
        if self.operation in keyed and self.key is None:
            raise ValueError(f"key is required for {self.operation}")
        if (
            self.operation in {"rotate_left", "rotate_right"}
            and self.key is not None
            and self.key > 7
        ):
            raise ValueError("rotation key must be between 0 and 7")
        return self


class DecodeStaticChainInput(Arguments):
    value: str = Field(
        min_length=1,
        max_length=512 * 1024,
        description="Bounded text/hex/Base64 input data; it is never executed.",
    )
    input_encoding: Literal["text", "hex", "base64"] = "text"
    steps: list[TransformStep] = Field(
        min_length=1, max_length=12, description="Ordered deterministic transform stages."
    )


class WritePythonScriptInput(Arguments):
    name: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$",
        description="Short decoder label used in a new append-only filename.",
    )
    objective: str = Field(
        min_length=3, max_length=4000, description="Exact decoding purpose for researcher review."
    )
    source: str = Field(
        min_length=1,
        max_length=MAX_SCRIPT_SOURCE_CHARACTERS,
        description="Complete Python source to parse, risk-scan, and save without executing it.",
    )
    inputs: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Expected case-relative input data paths; files are not opened by this call.",
    )
    expected_outputs: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Expected case-relative output paths; files are not created by this call.",
    )
    related_state_ids: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Related Finding, TODO, or checkpoint IDs for provenance.",
    )

    @field_validator("inputs", "expected_outputs")
    @classmethod
    def validate_provenance_paths(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 4096 or "\x00" in value for value in values):
            raise ValueError("provenance paths must contain 1-4096 characters and no null bytes")
        if any(_unsafe_provenance_path(value) for value in values):
            raise ValueError("provenance paths must be case-relative and cannot contain '..'")
        return values

    @field_validator("related_state_ids")
    @classmethod
    def validate_related_state_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 200 or "\x00" in value for value in values):
            raise ValueError("related state IDs must contain 1-200 characters and no null bytes")
        return values


class ListPythonScriptsInput(Arguments):
    limit: int = Field(default=100, ge=1, le=500)


def build_code_index(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = BuildCodeIndexInput.model_validate(arguments)
    root = context.read_path(values.path)
    if not root.is_file() and not root.is_dir():
        raise ValueError("path must resolve to a source file or directory")
    deadline = _deadline(context)
    index_path = _code_index_path(context)
    temporary = index_path.with_name(f".{index_path.name}.{uuid.uuid4().hex}.tmp")
    connection = sqlite3.connect(temporary)
    files_indexed = 0
    entries_indexed = 0
    skipped_binary = 0
    skipped_large = 0
    skipped_generated_scripts = 0
    bytes_scanned = 0
    scan_complete = True
    truncation_reason: str | None = None
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE files (
                path TEXT PRIMARY KEY,
                language TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                bytes_scanned INTEGER NOT NULL,
                complete INTEGER NOT NULL
            );
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                line INTEGER,
                kind TEXT NOT NULL,
                subtype TEXT NOT NULL,
                name TEXT NOT NULL
            );
            CREATE INDEX entries_name ON entries(name);
            CREATE INDEX entries_kind ON entries(kind, subtype);
            CREATE INDEX entries_path ON entries(path);
            """
        )
        for path in _source_entries(root):
            if root == context.case.root and path.is_relative_to(
                context.case.root / "workspace" / "scripts"
            ):
                skipped_generated_scripts += 1
                continue
            if time.monotonic() >= deadline:
                scan_complete = False
                truncation_reason = "time_budget"
                break
            if files_indexed >= values.max_files:
                scan_complete = False
                truncation_reason = "file_budget"
                break
            remaining_total = values.max_total_bytes - bytes_scanned
            if remaining_total <= 0:
                scan_complete = False
                truncation_reason = "total_byte_budget"
                break
            size = path.stat().st_size
            file_budget = min(size, values.max_file_bytes, remaining_total)
            remaining_entries = values.max_entries - entries_indexed
            if remaining_entries <= 1:
                scan_complete = False
                truncation_reason = "entry_budget"
                break
            scanned, records, file_complete, binary = _scan_source_file(
                path,
                file_budget,
                remaining_entries - 1,
                deadline,
            )
            display = _display_path(root, values.path, path)
            if binary:
                skipped_binary += 1
                continue
            if size > values.max_file_bytes:
                skipped_large += 1
            stat_result = path.stat()
            connection.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
                (
                    display,
                    LANGUAGES.get(path.suffix.lower(), "unknown"),
                    size,
                    stat_result.st_mtime_ns,
                    scanned,
                    int(file_complete),
                ),
            )
            connection.execute(
                "INSERT INTO entries(path, line, kind, subtype, name) VALUES (?, ?, 'file', 'source', ?)",
                (display, 1, path.name),
            )
            for line, kind, subtype, name in records:
                connection.execute(
                    "INSERT INTO entries(path, line, kind, subtype, name) VALUES (?, ?, ?, ?, ?)",
                    (display, line, kind, subtype, name[:1000]),
                )
            files_indexed += 1
            entries_indexed += len(records) + 1
            bytes_scanned += scanned
            if not file_complete:
                scan_complete = False
                if truncation_reason is None:
                    truncation_reason = (
                        "time_budget"
                        if time.monotonic() >= deadline
                        else "file_or_total_byte_budget"
                    )
            if entries_indexed >= values.max_entries:
                scan_complete = False
                truncation_reason = "entry_budget"
                break
        metadata = {
            "built_at": now_iso(),
            "requested_root": values.path,
            "source_content_stored": "false",
            "scan_complete": json.dumps(scan_complete),
        }
        connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        connection.commit()
        connection.close()
        os.chmod(temporary, 0o600)
        os.replace(temporary, index_path)
    except Exception:
        with suppress(Exception):
            connection.close()
        temporary.unlink(missing_ok=True)
        raise
    return {
        "index_path": CODE_INDEX_PATH,
        "requested_root": values.path,
        "files_indexed": files_indexed,
        "entries_indexed": entries_indexed,
        "bytes_scanned": bytes_scanned,
        "skipped_binary_files": skipped_binary,
        "skipped_generated_scripts": skipped_generated_scripts,
        "files_larger_than_per_file_budget": skipped_large,
        "scan_complete": scan_complete,
        "truncation_reason": truncation_reason,
        "source_content_stored": False,
        "accuracy": (
            "This is a contentless lexical index of source files, declarations, imports, and "
            "high-signal primitives; it is not a parsed call graph or reachability proof."
        ),
    }


def query_code_index(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = QueryCodeIndexInput.model_validate(arguments)
    try:
        index_path = context.read_path(CODE_INDEX_PATH)
    except Exception as exc:
        raise ValueError("No code index exists; run MalDroid_build_code_index first") from exc
    uri = index_path.as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    try:
        clauses = ["instr(lower(name), lower(?)) > 0"]
        parameters: list[Any] = [values.query]
        if values.kind != "any":
            clauses.append("kind = ?")
            parameters.append(values.kind)
        if values.path_prefix:
            clauses.append("path LIKE ? ESCAPE '\\'")
            escaped = (
                values.path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            parameters.append(escaped.rstrip("/") + "%")
        where = " AND ".join(clauses)
        total = int(
            connection.execute(
                f"SELECT COUNT(*) FROM entries WHERE {where}", parameters
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"SELECT path, line, kind, subtype, name FROM entries WHERE {where} "
            "ORDER BY CASE kind WHEN 'declaration' THEN 0 WHEN 'import' THEN 1 "
            "WHEN 'signal' THEN 2 ELSE 3 END, path, line LIMIT ?",
            (*parameters, values.limit),
        ).fetchall()
        metadata = {
            str(row["key"]): str(row["value"])
            for row in connection.execute("SELECT key, value FROM metadata")
        }
        file_rows = (
            {
                str(row["path"]): row
                for row in connection.execute(
                    "SELECT path, size, mtime_ns, complete FROM files WHERE path IN ("
                    + ",".join("?" for _ in rows)
                    + ")",
                    [str(row["path"]) for row in rows],
                )
            }
            if rows
            else {}
        )
    finally:
        connection.close()
    results: list[dict[str, Any]] = []
    stale_results = 0
    for row in rows:
        path_value = str(row["path"])
        indexed_file = file_rows.get(path_value)
        stale = True
        if indexed_file is not None:
            try:
                current = context.read_path(path_value).stat()
                stale = current.st_size != int(indexed_file["size"]) or current.st_mtime_ns != int(
                    indexed_file["mtime_ns"]
                )
            except Exception:
                stale = True
        stale_results += int(stale)
        results.append(
            {
                "path": path_value,
                "line": row["line"],
                "kind": row["kind"],
                "subtype": row["subtype"],
                "name": row["name"],
                "stale": stale,
                "file_fully_indexed": bool(indexed_file["complete"]) if indexed_file else False,
            }
        )
    return {
        "index_path": CODE_INDEX_PATH,
        "built_at": metadata.get("built_at"),
        "query": values.query,
        "kind": values.kind,
        "total_matches": total,
        "returned_matches": len(results),
        "truncated": total > len(results),
        "stale_results": stale_results,
        "freshness_basis": "indexed size and mtime_ns for returned files",
        "results": results,
        "accuracy": "Index matches are lexical leads; verify them with bounded source reads.",
    }


def read_code_context(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReadCodeContextInput.model_validate(arguments)
    path = _require_text_file(context, values.path)
    deadline = _deadline(context)
    target_line = values.line
    match_preview = ""
    occurrence_count = None
    scan_complete = True
    if values.symbol is not None:
        occurrence_count, matches, scan_complete = search_text_file_lines(
            path,
            values.symbol,
            case_sensitive=True,
            max_results=values.occurrence,
            deadline=deadline,
        )
        if len(matches) < values.occurrence:
            raise ValueError(
                f"Symbol occurrence {values.occurrence} was not found; "
                f"found {occurrence_count} matching logical lines"
            )
        target_line, match_preview = matches[values.occurrence - 1]
    assert target_line is not None
    start_line = max(1, target_line - values.before_lines)
    end_line = target_line + values.after_lines
    lines, content_truncated, budget_exhausted = read_text_range_bounded(
        path,
        start_line,
        end_line,
        values.max_characters,
        deadline=deadline,
    )
    return {
        "path": values.path,
        "symbol": values.symbol,
        "selected_occurrence": values.occurrence if values.symbol else None,
        "matching_logical_lines": occurrence_count,
        "symbol_scan_complete": scan_complete,
        "target_line": target_line,
        "start_line": start_line,
        "end_line_requested": end_line,
        "returned_lines": lines,
        "match_preview": match_preview,
        "content_truncated": content_truncated,
        "content_budget_exhausted": budget_exhausted,
        "whole_file_read": False,
        "accuracy": "The selected range is lexical context, not a parsed function boundary.",
    }


def analyze_obfuscation(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = AnalyzeObfuscationInput.model_validate(arguments)
    path = _require_text_file(context, values.path)
    size = path.stat().st_size
    deadline = _deadline(context)
    bytes_scanned = 0
    line_count = 0
    carry = ""
    candidates: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    candidate_seen: set[tuple[str, int, str]] = set()
    signal_seen: set[tuple[str, int]] = set()
    with path.open("rb") as handle:
        while bytes_scanned < min(size, values.max_scan_bytes):
            if time.monotonic() >= deadline:
                break
            raw = handle.read(min(65536, values.max_scan_bytes - bytes_scanned))
            if not raw:
                break
            if bytes_scanned == 0 and b"\x00" in raw[:8192]:
                raise ValueError("analyze_obfuscation requires decoded text/source")
            decoded = raw.decode("utf-8", errors="replace")
            text = carry + decoded
            first_line = max(1, line_count - carry.count("\n") + 1)
            if len(candidates) < values.max_candidates:
                for encoding, pattern in ENCODED_PATTERNS:
                    for match in pattern.finditer(text):
                        line = first_line + text[: match.start()].count("\n")
                        value = match.group(0)
                        fingerprint = hashlib.sha256(value.encode()).hexdigest()[:16]
                        key = (encoding, line, fingerprint)
                        if key in candidate_seen:
                            continue
                        candidate_seen.add(key)
                        record = _encoded_candidate(encoding, value, line)
                        if record is not None:
                            candidates.append(record)
                        if len(candidates) >= values.max_candidates:
                            break
                    if len(candidates) >= values.max_candidates:
                        break
            if len(signals) < values.max_signals:
                for signal, description, pattern in DECODE_SIGNAL_PATTERNS:
                    for match in pattern.finditer(text):
                        line = first_line + text[: match.start()].count("\n")
                        signal_key = (signal, line)
                        if signal_key in signal_seen:
                            continue
                        signal_seen.add(signal_key)
                        signals.append(
                            {
                                "signal": signal,
                                "description": description,
                                "line": line,
                                "match": match.group(0)[:200],
                                "preview": text[
                                    max(0, match.start() - 120) : match.end() + 180
                                ].replace("\n", " ")[:500],
                            }
                        )
                        if len(signals) >= values.max_signals:
                            break
                    if len(signals) >= values.max_signals:
                        break
            bytes_scanned += len(raw)
            line_count += decoded.count("\n")
            carry = text[-SOURCE_SCAN_OVERLAP:]
    scan_complete = bytes_scanned >= size
    return {
        "path": values.path,
        "file_size": size,
        "bytes_scanned": bytes_scanned,
        "scan_complete": scan_complete,
        "truncation_reason": None
        if scan_complete
        else "time_budget"
        if time.monotonic() >= deadline
        else "byte_budget",
        "candidate_count": len(candidates),
        "candidates_truncated": len(candidates) >= values.max_candidates,
        "candidates": candidates,
        "decode_signal_count": len(signals),
        "decode_signals_truncated": len(signals) >= values.max_signals,
        "decode_signals": signals,
        "executed": False,
        "accuracy": (
            "Candidates and pipelines are lexical/encoding heuristics. High entropy alone does "
            "not prove encryption; verify each transform and caller before making a Finding."
        ),
    }


def decode_static_chain(_: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = DecodeStaticChainInput.model_validate(arguments)
    data = _initial_transform_bytes(values.value, values.input_encoding)
    provenance: list[dict[str, Any]] = []
    for position, step in enumerate(values.steps, start=1):
        input_hash = hashlib.sha256(data).hexdigest()
        input_bytes = len(data)
        data = _apply_transform(data, step)
        if len(data) > MAX_TRANSFORM_OUTPUT_BYTES:
            raise ValueError(
                f"Transform {position} ({step.operation}) exceeded the {MAX_TRANSFORM_OUTPUT_BYTES}-byte output limit"
            )
        provenance.append(
            {
                "step": position,
                "operation": step.operation,
                "key": step.key,
                "input_bytes": input_bytes,
                "input_sha256": input_hash,
                "output_bytes": len(data),
                "output_sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {
        "input_encoding": values.input_encoding,
        "provenance": provenance,
        "final": _bytes_preview(data),
        "executed": False,
        "safety": "Every stage transformed bounded bytes as data; no decoded content was executed.",
    }


def write_python_script(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = WritePythonScriptInput.model_validate(arguments)
    try:
        tree = ast.parse(values.source, filename=f"{values.name}.py", mode="exec")
    except SyntaxError as exc:
        location = f"line {exc.lineno}, column {exc.offset}" if exc.lineno else "unknown line"
        raise ValueError(f"Python syntax is invalid at {location}: {exc.msg}") from exc
    risk_findings, imports = _scan_python_risk(tree)
    blocked = any(item["severity"] == "blocked" for item in risk_findings)
    if blocked:
        return {
            "prepared": False,
            "risk_level": "blocked",
            "risk_findings": risk_findings,
            "imports": imports,
            "instruction": (
                "Remove process, network, dynamic-execution, native-loading, or destructive "
                "capabilities and submit a decoding-only script. No file was written."
            ),
            "execution_status": "not_executed",
        }
    directory = _script_directory(context, create=True)
    assert directory is not None
    sequence = _next_script_sequence(directory)
    script_id = f"SCRIPT-{sequence:04d}"
    slug = _slug(values.name)
    script_relative = f"workspace/scripts/{script_id}-{slug}.py"
    manifest_relative = f"workspace/scripts/{script_id}-{slug}.json"
    script_path = context.path_policy.resolve_write(script_relative)
    manifest_path = context.path_policy.resolve_write(manifest_relative)
    if script_path.exists() or manifest_path.exists():
        raise ValueError("The next script revision already exists; retry to allocate a new ID")
    header = (
        "# Prepared by MalDroid for researcher review.\n"
        "# NOT EXECUTED BY MALDROID. Review inputs, outputs, and every operation before manual use.\n\n"
    )
    persisted_source = header + values.source
    if not persisted_source.endswith("\n"):
        persisted_source += "\n"
    source_sha256 = hashlib.sha256(persisted_source.encode("utf-8")).hexdigest()
    model_source_sha256 = hashlib.sha256(values.source.encode("utf-8")).hexdigest()
    risk_level = "review" if risk_findings else "low"
    packages = _package_provenance(imports)
    created_at = now_iso()
    manifest = {
        "schema_version": 1,
        "script_id": script_id,
        "name": values.name,
        "objective": values.objective,
        "creator": "local_model_or_mcp_client",
        "created_at": created_at,
        "path": script_relative,
        "source_sha256": source_sha256,
        "model_source_sha256": model_source_sha256,
        "python_version": platform.python_version(),
        "prepared_in_virtual_environment": sys.prefix != sys.base_prefix,
        "imports": imports,
        "packages": packages,
        "inputs": values.inputs,
        "expected_outputs": values.expected_outputs,
        "related_state_ids": values.related_state_ids,
        "approval_mode": "review_only",
        "risk": {"level": risk_level, "findings": risk_findings, "static_scan_only": True},
        "execution": {
            "status": "not_executed",
            "exit_code": None,
            "started_at": None,
            "completed_at": None,
            "authority": "none",
        },
    }
    try:
        artifact_lock = _artifact_lock_path(context)
        atomic_write_text(script_path, persisted_source, mode=0o600, lock_path=artifact_lock)
        atomic_write_json(manifest_path, manifest, lock_path=artifact_lock)
    except Exception:
        script_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise
    diff_lines = difflib.unified_diff(
        [],
        persisted_source.splitlines(),
        fromfile="/dev/null",
        tofile=script_relative,
        lineterm="",
    )
    diff = "\n".join(diff_lines)
    diff_truncated = len(diff) > 12000
    return {
        "prepared": True,
        "script_id": script_id,
        "purpose": values.objective,
        "path": script_relative,
        "manifest_path": manifest_relative,
        "source_sha256": source_sha256,
        "model_source_sha256": model_source_sha256,
        "syntax_valid": True,
        "risk_level": risk_level,
        "risk_findings": risk_findings,
        "imports": imports,
        "packages": packages,
        "diff": diff[:12000],
        "diff_truncated": diff_truncated,
        "execution_status": "not_executed",
        "instruction": (
            "Tell the researcher that the Python decoder was prepared at the returned path and "
            "was not executed. It requires manual source review before any external use."
        ),
    }


def list_python_scripts(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ListPythonScriptsInput.model_validate(arguments)
    directory = _script_directory(context, create=False)
    if directory is None:
        return {"script_count": 0, "returned_scripts": 0, "scripts": []}
    scripts: list[dict[str, Any]] = []
    invalid_manifests = 0
    manifests = sorted(directory.glob("SCRIPT-*.json"))
    for path in manifests[-values.limit :]:
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("manifest must be a regular case-local file")
            if path.stat().st_size > MIB:
                raise ValueError("manifest is larger than 1 MiB")
            value = json.loads(path.read_text(encoding="utf-8"))
            execution = value.get("execution", {})
            risk = value.get("risk", {})
            scripts.append(
                {
                    "script_id": value.get("script_id"),
                    "name": value.get("name"),
                    "objective": value.get("objective"),
                    "path": value.get("path"),
                    "created_at": value.get("created_at"),
                    "source_sha256": value.get("source_sha256"),
                    "risk_level": risk.get("level"),
                    "execution_status": execution.get("status", "unknown"),
                }
            )
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            invalid_manifests += 1
    return {
        "script_count": len(manifests),
        "returned_scripts": len(scripts),
        "truncated": len(manifests) > len(scripts) + invalid_manifests,
        "invalid_manifests": invalid_manifests,
        "scripts": scripts,
        "execution_authority": "none",
    }


def register_code_analysis_tools(registry: ToolRegistry) -> None:
    definitions: list[tuple[str, str, type[BaseModel], ToolHandler]] = [
        (
            "build_code_index",
            "Build a bounded contentless index of source files, declarations, imports, and high-signal primitives.",
            BuildCodeIndexInput,
            build_code_index,
        ),
        (
            "query_code_index",
            "Query the case source index for files, declarations, imports, or static-analysis signals.",
            QueryCodeIndexInput,
            query_code_index,
        ),
        (
            "read_code_context",
            "Find a symbol or line and return bounded nearby source plus a match-centered minified-code preview.",
            ReadCodeContextInput,
            read_code_context,
        ),
        (
            "analyze_obfuscation",
            "Detect bounded encoded literals, decoding operations, XOR, compression, and cryptographic leads in source.",
            AnalyzeObfuscationInput,
            analyze_obfuscation,
        ),
        (
            "decode_static_chain",
            "Apply a bounded provenance-rich chain of encoding, byte, XOR, rotation, or decompression transforms as data only.",
            DecodeStaticChainInput,
            decode_static_chain,
        ),
        (
            "write_python_script",
            "Prepare a review-only case-local Python decoding script with provenance and static risk scanning; never execute it.",
            WritePythonScriptInput,
            write_python_script,
        ),
        (
            "list_python_scripts",
            "List prepared case-local Python script manifests and confirm their execution status.",
            ListPythonScriptsInput,
            list_python_scripts,
        ),
    ]
    for name, description, model, handler in definitions:
        registry.register(ToolDefinition(name, "core", description, model, handler))


def _source_entries(root: Path) -> Any:
    if root.is_file():
        if root.suffix.lower() in SOURCE_SUFFIXES and not root.is_symlink():
            yield root
        return
    for path in walk_regular_entries(root):
        if path.suffix.lower() in SOURCE_SUFFIXES:
            yield path


def _code_index_path(context: ToolContext) -> Path:
    internal = context.case.root / ".maldroid"
    if internal.is_symlink() or not internal.is_dir():
        raise ValueError("The case metadata directory must be a real directory")
    indexes = internal / "indexes"
    if indexes.is_symlink():
        raise ValueError("The code-index directory cannot be a symbolic link")
    if not indexes.exists():
        indexes = context.path_policy.resolve_write(".maldroid/indexes")
        indexes.mkdir(mode=0o700)
    if not indexes.is_dir():
        raise ValueError(".maldroid/indexes must be a directory")
    return context.path_policy.resolve_write(CODE_INDEX_PATH)


def _scan_source_file(
    path: Path,
    byte_budget: int,
    entry_budget: int,
    deadline: float,
) -> tuple[int, list[tuple[int, str, str, str]], bool, bool]:
    records: list[tuple[int, str, str, str]] = []
    seen: set[tuple[int, str, str, str]] = set()
    scanned = 0
    line_count = 0
    carry = ""
    binary = False
    with path.open("rb") as handle:
        while scanned < byte_budget and len(records) < entry_budget:
            if time.monotonic() >= deadline:
                break
            raw = handle.read(min(65536, byte_budget - scanned))
            if not raw:
                break
            if scanned == 0 and b"\x00" in raw[:8192]:
                binary = True
                break
            decoded = raw.decode("utf-8", errors="replace")
            text = carry + decoded
            first_line = max(1, line_count - carry.count("\n") + 1)
            for pattern in IMPORT_PATTERNS:
                for match in pattern.finditer(text):
                    module = next((group for group in match.groups() if group), "")
                    if not module:
                        continue
                    line = first_line + text[: match.start()].count("\n")
                    record = (line, "import", "module", module)
                    if record not in seen:
                        seen.add(record)
                        records.append(record)
                    if len(records) >= entry_budget:
                        break
                if len(records) >= entry_budget:
                    break
            if len(records) < entry_budget:
                for subtype, pattern in DECLARATION_PATTERNS:
                    for match in pattern.finditer(text):
                        line = first_line + text[: match.start()].count("\n")
                        record = (line, "declaration", subtype, match.group(1))
                        if record not in seen:
                            seen.add(record)
                            records.append(record)
                        if len(records) >= entry_budget:
                            break
                    if len(records) >= entry_budget:
                        break
            if len(records) < entry_budget:
                for subtype, pattern in SIGNAL_PATTERNS.items():
                    for match in pattern.finditer(text):
                        line = first_line + text[: match.start()].count("\n")
                        record = (line, "signal", subtype, match.group(0))
                        if record not in seen:
                            seen.add(record)
                            records.append(record)
                        if len(records) >= entry_budget:
                            break
                    if len(records) >= entry_budget:
                        break
            scanned += len(raw)
            line_count += decoded.count("\n")
            carry = text[-SOURCE_SCAN_OVERLAP:]
    complete = (
        scanned >= path.stat().st_size
        and len(records) < entry_budget
        and time.monotonic() < deadline
    )
    return scanned, records, complete, binary


def _display_path(root: Path, requested: str, path: Path) -> str:
    if root.is_file():
        return requested
    relative = path.relative_to(root).as_posix()
    return relative if requested == "." else (Path(requested) / relative).as_posix()


def _require_text_file(context: ToolContext, requested: str) -> Path:
    path = context.read_path(requested)
    if not path.is_file():
        raise ValueError("A regular source file is required")
    with path.open("rb") as handle:
        if b"\x00" in handle.read(8192):
            raise ValueError("This tool requires decoded text/source, not a binary container")
    return path


def _deadline(context: ToolContext) -> float:
    return time.monotonic() + context.config.limits.command_timeout_seconds


def _encoded_candidate(encoding: str, value: str, line: int) -> dict[str, Any] | None:
    try:
        if encoding == "hex":
            decoded = bytes.fromhex(value)
        elif encoding == "base64":
            compact = value + "=" * (-len(value) % 4)
            decoded = base64.b64decode(compact, altchars=b"-_", validate=True)
            if len(set(value.rstrip("="))) < 6:
                return None
        elif encoding == "url":
            decoded = unquote_to_bytes(value)
        else:
            decoded_text = re.sub(
                r"\\u([0-9A-Fa-f]{4})",
                lambda match: chr(int(match.group(1), 16)),
                value,
            )
            decoded = decoded_text.encode("utf-8")
    except (ValueError, UnicodeError):
        return None
    printable = sum(byte in b"\t\n\r" or 32 <= byte < 127 for byte in decoded)
    printable_ratio = printable / max(1, len(decoded))
    confidence = "high" if printable_ratio >= 0.8 else "medium" if printable_ratio >= 0.4 else "low"
    preview = _bytes_preview(decoded, text_limit=1000, hex_limit=128)
    return {
        "encoding": encoding,
        "line": line,
        "encoded_characters": len(value),
        "encoded_sha256": hashlib.sha256(value.encode()).hexdigest(),
        "decoded_bytes": len(decoded),
        "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
        "decoded_printable_ratio": round(printable_ratio, 4),
        "decoded_entropy_bits_per_byte": round(_entropy(decoded), 4),
        "confidence": confidence,
        "source_preview": value[:160] + ("…" if len(value) > 160 else ""),
        "decoded_preview": preview,
    }


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in Counter(data).values())


def _initial_transform_bytes(value: str, encoding: str) -> bytes:
    if encoding == "text":
        return value.encode("utf-8")
    if encoding == "hex":
        try:
            return bytes.fromhex(value)
        except ValueError:
            raise ValueError("value is not valid hexadecimal input") from None
    return _decode_base64(value.encode("ascii", errors="strict"))


def _apply_transform(data: bytes, step: TransformStep) -> bytes:
    operation = step.operation
    try:
        if operation == "base64":
            return _decode_base64(data)
        if operation == "base32":
            compact = re.sub(rb"\s+", b"", data).upper()
            return base64.b32decode(compact + b"=" * (-len(compact) % 8), casefold=True)
        if operation == "hex":
            return bytes.fromhex(data.decode("ascii"))
        if operation == "url":
            return unquote_to_bytes(data.decode("utf-8"))
        if operation == "unicode_escape":
            return codecs.decode(data.decode("utf-8"), "unicode_escape").encode("utf-8")
        if operation == "rot13":
            return codecs.decode(data.decode("utf-8"), "rot_13").encode("utf-8")
        if operation == "reverse":
            return data[::-1]
        if operation == "xor":
            assert step.key is not None
            return bytes(byte ^ step.key for byte in data)
        if operation == "add":
            assert step.key is not None
            return bytes((byte + step.key) & 0xFF for byte in data)
        if operation == "subtract":
            assert step.key is not None
            return bytes((byte - step.key) & 0xFF for byte in data)
        if operation == "rotate_left":
            assert step.key is not None
            return bytes(_rotate_left(byte, step.key) for byte in data)
        if operation == "rotate_right":
            assert step.key is not None
            return bytes(_rotate_right(byte, step.key) for byte in data)
        if operation == "gzip":
            return _bounded_zlib(data, 16 + zlib.MAX_WBITS)
        if operation == "zlib":
            return _bounded_zlib(data, zlib.MAX_WBITS)
        if operation == "bz2":
            bz2_decompressor = bz2.BZ2Decompressor()
            output = bz2_decompressor.decompress(data, max_length=MAX_TRANSFORM_OUTPUT_BYTES + 1)
            if len(output) > MAX_TRANSFORM_OUTPUT_BYTES or not bz2_decompressor.eof:
                raise ValueError("decompressed output limit exceeded or stream is incomplete")
            if bz2_decompressor.unused_data:
                raise ValueError("trailing or concatenated bzip2 data is unsupported")
            return output
        if operation == "lzma":
            lzma_decompressor = lzma.LZMADecompressor(memlimit=MAX_LZMA_MEMORY_BYTES)
            output = lzma_decompressor.decompress(data, max_length=MAX_TRANSFORM_OUTPUT_BYTES + 1)
            if len(output) > MAX_TRANSFORM_OUTPUT_BYTES or not lzma_decompressor.eof:
                raise ValueError("decompressed output limit exceeded or stream is incomplete")
            if lzma_decompressor.unused_data:
                raise ValueError("trailing or concatenated LZMA/XZ data is unsupported")
            return output
    except (ValueError, UnicodeError, zlib.error, lzma.LZMAError, OSError) as exc:
        raise ValueError(f"{operation} transform failed: {exc}") from exc
    raise ValueError(f"Unsupported transform: {operation}")


def _decode_base64(data: bytes) -> bytes:
    compact = re.sub(rb"\s+", b"", data)
    compact += b"=" * (-len(compact) % 4)
    try:
        return base64.b64decode(compact, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("input is not valid Base64") from exc


def _bounded_zlib(data: bytes, window_bits: int) -> bytes:
    decompressor = zlib.decompressobj(window_bits)
    output = decompressor.decompress(data, MAX_TRANSFORM_OUTPUT_BYTES + 1)
    if len(output) > MAX_TRANSFORM_OUTPUT_BYTES or decompressor.unconsumed_tail:
        raise ValueError("decompressed output limit exceeded")
    remaining = MAX_TRANSFORM_OUTPUT_BYTES + 1 - len(output)
    if remaining > 0:
        output += decompressor.flush(remaining)
    if len(output) > MAX_TRANSFORM_OUTPUT_BYTES:
        raise ValueError("decompressed output limit exceeded")
    if not decompressor.eof:
        raise ValueError("compressed stream is incomplete")
    if decompressor.unused_data:
        raise ValueError("trailing or concatenated compressed data is unsupported")
    return output


def _rotate_left(value: int, amount: int) -> int:
    return ((value << amount) | (value >> (8 - amount))) & 0xFF if amount else value


def _rotate_right(value: int, amount: int) -> int:
    return ((value >> amount) | (value << (8 - amount))) & 0xFF if amount else value


def _bytes_preview(data: bytes, text_limit: int = 32768, hex_limit: int = 512) -> dict[str, Any]:
    limited = data[:text_limit]
    return {
        "bytes": len(data),
        "truncated": len(data) > len(limited),
        "utf8_preview": limited.decode("utf-8", errors="replace"),
        "hex_preview": data[:hex_limit].hex(" "),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _scan_python_risk(tree: ast.AST) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    imports: set[str] = set()
    aliases: dict[str, str] = {}

    def add(severity: str, category: str, message: str, line: int | None) -> None:
        record = {"severity": severity, "category": category, "message": message, "line": line}
        if record not in findings:
            findings.append(record)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                imports.add(item.name)
                aliases[item.asname or item.name.split(".")[0]] = item.name
                blocked = _blocked_import_category(item.name)
                if blocked:
                    add("blocked", blocked, f"Import {item.name} enables {blocked}.", node.lineno)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.add(module)
            for item in node.names:
                imported_name = f"{module}.{item.name}".strip(".")
                aliases[item.asname or item.name] = imported_name
                item_blocked = _blocked_import_category(imported_name)
                if item_blocked:
                    add(
                        "blocked",
                        item_blocked,
                        f"Import {imported_name} enables {item_blocked}.",
                        node.lineno,
                    )
            blocked = _blocked_import_category(module)
            if blocked:
                add("blocked", blocked, f"Import {module} enables {blocked}.", node.lineno)
        elif isinstance(node, ast.Call):
            qualified = _qualified_call_name(node.func, aliases)
            method = qualified.rsplit(".", 1)[-1]
            blocked = (
                BLOCKED_CALLS.get(qualified)
                or BLOCKED_CALLS.get(method)
                or _blocked_import_category(qualified)
            )
            if blocked:
                add("blocked", blocked, f"Call {qualified} enables {blocked}.", node.lineno)
            elif qualified in {"os.getenv", "pathlib.Path.home", "Path.home"}:
                add(
                    "blocked",
                    "host data access",
                    f"Call {qualified} reads host state.",
                    node.lineno,
                )
            elif method in BLOCKED_METHODS:
                add(
                    "blocked",
                    "destructive or network operation",
                    f"Call {qualified} is not allowed.",
                    node.lineno,
                )
            elif method in WRITE_METHODS:
                add(
                    "review",
                    "filesystem output",
                    f"Call {qualified} can write data; verify its destination before manual use.",
                    node.lineno,
                )
            if (
                (qualified in PATH_ARGUMENT_CALLS or method in PATH_ARGUMENT_CALLS)
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                first_argument = node.args[0].value
                if isinstance(first_argument, str) and _unsafe_script_literal_path(first_argument):
                    add(
                        "blocked",
                        "case-boundary risk",
                        f"Call {qualified} contains an absolute or parent-traversing path.",
                        node.lineno,
                    )
        elif isinstance(node, ast.Attribute):
            qualified = _qualified_call_name(node, aliases)
            if qualified == "os.environ":
                add(
                    "blocked",
                    "host data access",
                    "Access to os.environ can expose host secrets.",
                    node.lineno,
                )
    findings.sort(key=lambda item: (item["line"] or 0, item["severity"], item["message"]))
    return findings, sorted(item for item in imports if item)


def _blocked_import_category(module: str) -> str | None:
    for blocked, category in BLOCKED_IMPORTS.items():
        if module == blocked or module.startswith(blocked + "."):
            return category
    return None


def _qualified_call_name(node: ast.expr, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_call_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _qualified_call_name(node.func, aliases)
    return "<dynamic>"


def _unsafe_script_literal_path(value: str) -> bool:
    path = Path(value)
    return path.is_absolute() or ".." in path.parts


def _unsafe_provenance_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        normalized.startswith("/")
        or bool(re.match(r"^[A-Za-z]:/", normalized))
        or ".." in Path(normalized).parts
    )


def _package_provenance(imports: list[str]) -> list[dict[str, Any]]:
    distribution_map = importlib.metadata.packages_distributions()
    packages: list[dict[str, Any]] = []
    for root in sorted({name.split(".", 1)[0] for name in imports if name}):
        if root in sys.stdlib_module_names:
            packages.append(
                {"import": root, "distribution": "stdlib", "version": platform.python_version()}
            )
            continue
        distributions = distribution_map.get(root, [])
        if not distributions:
            packages.append({"import": root, "distribution": None, "version": "not_verified"})
            continue
        for distribution in sorted(distributions):
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                version = "not_verified"
            packages.append({"import": root, "distribution": distribution, "version": version})
    return packages


def _script_directory(context: ToolContext, *, create: bool) -> Path | None:
    workspace = context.case.root / "workspace"
    if workspace.is_symlink():
        raise ValueError("The workspace directory cannot be a symbolic link")
    if not workspace.exists():
        if not create:
            return None
        workspace = context.path_policy.resolve_write("workspace")
        workspace.mkdir(mode=0o700)
    if not workspace.is_dir():
        raise ValueError("workspace must be a directory")
    scripts = workspace / "scripts"
    if scripts.is_symlink():
        raise ValueError("The script directory cannot be a symbolic link")
    if not scripts.exists():
        if not create:
            return None
        scripts = context.path_policy.resolve_write("workspace/scripts")
        scripts.mkdir(mode=0o700)
    if not scripts.is_dir():
        raise ValueError("workspace/scripts must be a directory")
    return context.read_path("workspace/scripts")


def _artifact_lock_path(context: ToolContext) -> Path:
    internal = context.case.root / ".maldroid"
    if internal.is_symlink() or not internal.is_dir():
        raise ValueError("The case metadata directory must be a real directory")
    locks = internal / "locks"
    if locks.is_symlink():
        raise ValueError("The case lock directory cannot be a symbolic link")
    if not locks.exists():
        locks = context.path_policy.resolve_write(".maldroid/locks")
        locks.mkdir(mode=0o700)
    if not locks.is_dir():
        raise ValueError(".maldroid/locks must be a directory")
    return context.path_policy.resolve_write(".maldroid/locks/code-artifacts.lock")


def _next_script_sequence(directory: Path) -> int:
    maximum = 0
    for path in directory.glob("SCRIPT-*.*"):
        match = re.match(r"SCRIPT-(\d{4,})-", path.name)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum + 1


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.").lower()
    return cleaned[:80] or "decoder"
