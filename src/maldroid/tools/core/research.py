"""High-value, bounded static-research tools for source and artifact inspection."""

from __future__ import annotations

import base64
import codecs
import configparser
import difflib
import hashlib
import itertools
import json
import math
import mimetypes
import plistlib
import re
import sqlite3
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import unquote_to_bytes

import yaml
from defusedxml import ElementTree as SafeElementTree
from pydantic import BaseModel, ConfigDict, Field, model_validator
from yaml.events import AliasEvent

from maldroid.io_utils import search_text_file_lines
from maldroid.paths import walk_regular_entries
from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry

MAX_STRUCTURED_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SOURCE_MAP_BYTES = 64 * 1024 * 1024
SOURCE_SUFFIXES = {
    ".asm",
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".cs",
    ".cxx",
    ".dart",
    ".go",
    ".groovy",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".m",
    ".mjs",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".s",
    ".scala",
    ".smali",
    ".sol",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathInput(Arguments):
    path: str


class InspectFileInput(PathInput):
    max_scan_bytes: int = Field(default=256 * 1024 * 1024, ge=4096, le=2 * 1024 * 1024 * 1024)


class InspectArchiveInput(PathInput):
    name_query: str | None = Field(default=None, min_length=1, max_length=500)
    max_entries: int = Field(default=500, ge=1, le=5000)


class ReadArchiveEntryInput(PathInput):
    entry: str = Field(min_length=1, max_length=4096)
    max_bytes: int = Field(default=65536, ge=1, le=65536)


StructuredFormat = Literal["auto", "json", "yaml", "plist", "xml", "ini"]


class StructuredDataInput(PathInput):
    format: StructuredFormat = "auto"
    query: str | None = Field(default=None, max_length=1000)
    max_nodes: int = Field(default=200, ge=1, le=2000)


class SqliteInput(PathInput):
    action: Literal["schema", "sample", "search"] = "schema"
    table: str | None = Field(default=None, max_length=500)
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def validate_action(self) -> SqliteInput:
        if self.action == "sample" and not self.table:
            raise ValueError("table is required for sample")
        if self.action == "search" and not self.query:
            raise ValueError("query is required for search")
        return self


class SourceSummaryInput(PathInput):
    max_results: int = Field(default=200, ge=10, le=1000)
    max_scan_bytes: int = Field(default=64 * 1024 * 1024, ge=65536, le=512 * 1024 * 1024)


class DependencyMapInput(Arguments):
    path: str = "."
    max_files: int = Field(default=10000, ge=1, le=50000)
    max_edges: int = Field(default=1000, ge=1, le=10000)
    max_bytes_per_file: int = Field(default=262144, ge=4096, le=4 * 1024 * 1024)


class TraceSymbolInput(Arguments):
    symbol: str = Field(min_length=1, max_length=300)
    path: str = "."
    case_sensitive: bool = True
    max_files: int = Field(default=20000, ge=1, le=50000)
    max_results: int = Field(default=200, ge=1, le=1000)


class CompareFilesInput(Arguments):
    left_path: str
    right_path: str
    max_diff_lines: int = Field(default=200, ge=1, le=1000)


class DecodeStaticInput(Arguments):
    value: str = Field(min_length=1, max_length=65536)
    operation: Literal["auto", "base64", "hex", "url", "rot13", "xor"] = "auto"
    input_encoding: Literal["text", "hex", "base64"] = "text"
    xor_key: int | None = Field(default=None, ge=0, le=255)

    @model_validator(mode="after")
    def require_xor_key(self) -> DecodeStaticInput:
        if self.operation == "xor" and self.xor_key is None:
            raise ValueError("xor_key is required for xor")
        return self


class ManifestInput(PathInput):
    max_components: int = Field(default=300, ge=1, le=2000)


class SourceMapInput(PathInput):
    source_query: str | None = Field(default=None, max_length=1000)
    include_content: bool = False
    max_sources: int = Field(default=200, ge=1, le=2000)


MAGIC_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x7fELF", "ELF executable/library", "application/x-elf"),
    (b"dex\n", "Android DEX", "application/vnd.android.dex"),
    (b"SQLite format 3\x00", "SQLite database", "application/vnd.sqlite3"),
    (b"PK\x03\x04", "ZIP-compatible archive", "application/zip"),
    (b"PK\x05\x06", "Empty ZIP-compatible archive", "application/zip"),
    (b"\x1f\x8b", "Gzip stream", "application/gzip"),
    (b"BZh", "Bzip2 stream", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "XZ stream", "application/x-xz"),
    (b"MZ", "Windows PE/DOS executable", "application/vnd.microsoft.portable-executable"),
    (b"\xca\xfe\xba\xbe", "Java class or Mach-O universal binary", "application/octet-stream"),
    (b"\xcf\xfa\xed\xfe", "Mach-O 64-bit binary", "application/x-mach-binary"),
    (b"\xfe\xed\xfa\xcf", "Mach-O 64-bit binary (big endian)", "application/x-mach-binary"),
    (b"%PDF-", "PDF document", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "PNG image", "image/png"),
)
EXPECTED_MAGIC_EXTENSIONS: dict[str, set[str]] = {
    "ELF executable/library": {"", ".bin", ".elf", ".so"},
    "Android DEX": {".dex"},
    "SQLite database": {".db", ".db3", ".sqlite", ".sqlite3"},
    "ZIP-compatible archive": {".aab", ".apk", ".apks", ".jar", ".zip"},
    "Empty ZIP-compatible archive": {".aab", ".apk", ".apks", ".jar", ".zip"},
    "Gzip stream": {".gz", ".gzip"},
    "Bzip2 stream": {".bz2"},
    "XZ stream": {".xz"},
    "Windows PE/DOS executable": {".dll", ".exe", ".sys"},
    "Java class or Mach-O universal binary": {".class", ".dylib"},
    "Mach-O 64-bit binary": {"", ".dylib"},
    "Mach-O 64-bit binary (big endian)": {"", ".dylib"},
    "PDF document": {".pdf"},
    "PNG image": {".png"},
}

LANGUAGES = {
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

IMPORT_PATTERNS = (
    re.compile(r"\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?[\"']([^\"']+)[\"']"),
    re.compile(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
    re.compile(r"(?m)^\s*import\s+([A-Za-z_][\w.]*)\s*;?"),
    re.compile(r"(?m)^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]"),
    re.compile(r"(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"),
    re.compile(r"(?m)^\s*use\s+([A-Za-z_][\w:]*)"),
    re.compile(r"(?m)^\s*(?:package|using)\s+([A-Za-z_][\w.]*)"),
)

DECLARATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "class",
        re.compile(r"\b(?:class|interface|object|enum|struct|trait)\s+([A-Za-z_$][\w$]*)"),
    ),
    ("function", re.compile(r"\b(?:function|fun|def)\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("function", re.compile(r"\bfn\s+([A-Za-z_$][\w$]*)\s*[<(]")),
    (
        "function",
        re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\("),
    ),
    (
        "function",
        re.compile(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        ),
    ),
    (
        "method",
        re.compile(
            r"(?m)^\s*(?:public|private|protected|static|final|native|synchronized|async|export|internal|open|override|virtual|inline|const|unsigned|signed|\s)+\s*[\w.$<>\[\],?*&:]+\s+([A-Za-z_$][\w$]*)\s*\("
        ),
    ),
    ("smali_method", re.compile(r"(?m)^\.method\s+[^\n]*?([A-Za-z_$<>][\w$<>]*)\(")),
    ("smali_class", re.compile(r"(?m)^\.class\s+[^\n]*?L([^;]+);")),
)

HIGH_SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "network": re.compile(r"\b(?:fetch|axios|XMLHttpRequest|OkHttp|Retrofit|connect|send|recv)\b"),
    "dynamic_code": re.compile(
        r"\b(?:eval|DexClassLoader|PathClassLoader|InMemoryDexClassLoader|dlopen|dlsym|loadLibrary)\b"
    ),
    "process": re.compile(r"\b(?:Runtime\.getRuntime|ProcessBuilder|execve|system|popen)\b"),
    "crypto": re.compile(r"\b(?:Cipher|getInstance|MessageDigest|SecretKeySpec|AES|RSA|ChaCha)\b"),
    "native_bridge": re.compile(
        r"\b(?:NativeModules|TurboModule|JNI_OnLoad|RegisterNatives|addJavascriptInterface)\b"
    ),
    "persistence": re.compile(
        r"\b(?:BOOT_COMPLETED|WorkManager|JobScheduler|startForeground|AccessibilityService)\b"
    ),
}


class _NoAliasSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise ValueError("YAML aliases are disabled for untrusted evidence")
        return super().compose_node(parent, index)


def inspect_file(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = InspectFileInput.model_validate(arguments)
    path = _require_file(context, values.path)
    size = path.stat().st_size
    deadline = _deadline(context)
    digests: dict[str, Any] = {
        "sha256": hashlib.sha256(),
        "sha1": hashlib.sha1(),  # noqa: S324 - malware identification, not trust
    }
    with suppress(ValueError):  # FIPS installations may disable MD5 entirely
        digests["md5"] = hashlib.md5(usedforsecurity=False)
    histogram: Counter[int] = Counter()
    scanned = 0
    first = b""
    last = b""
    complete = True
    with path.open("rb") as handle:
        while scanned < min(size, values.max_scan_bytes):
            if time.monotonic() >= deadline:
                complete = False
                break
            block = handle.read(min(1024 * 1024, values.max_scan_bytes - scanned))
            if not block:
                break
            if not first:
                first = block[:65536]
            last = (last + block)[-64:]
            for digest in digests.values():
                digest.update(block)
            histogram.update(block)
            scanned += len(block)
    if scanned < size:
        complete = False
    entropy = 0.0
    if scanned:
        entropy = -sum(
            (count / scanned) * math.log2(count / scanned) for count in histogram.values()
        )
    signature = next(
        ((label, mime) for magic, label, mime in MAGIC_SIGNATURES if first.startswith(magic)),
        None,
    )
    guessed_mime = mimetypes.guess_type(path.name)[0]
    extension = path.suffix.lower()
    expected_extensions = EXPECTED_MAGIC_EXTENSIONS.get(signature[0], set()) if signature else set()
    result: dict[str, Any] = {
        "path": values.path,
        "size": size,
        "bytes_scanned": scanned,
        "scan_complete": complete,
        "truncation_reason": None
        if complete
        else "time_budget"
        if scanned < min(size, values.max_scan_bytes)
        else "byte_budget",
        "format": signature[0] if signature else "unknown",
        "format_confidence": "high"
        if signature and " or " not in signature[0]
        else "medium"
        if signature
        else "low",
        "mime_type": signature[1] if signature else guessed_mime,
        "extension": extension,
        "expected_extensions": sorted(expected_extensions),
        "extension_conflicts_with_magic": bool(
            signature and expected_extensions and extension not in expected_extensions
        ),
        "language": LANGUAGES.get(extension),
        "encoding": _detect_encoding(first),
        "entropy_bits_per_byte": round(entropy, 4),
        "unique_byte_values": len(histogram),
        "first_32_bytes_hex": first[:32].hex(" "),
        "last_32_bytes_hex": last[-32:].hex(" "),
        "hash_scope": "complete_file" if complete else "not_reported_for_partial_scan",
    }
    if complete:
        result["hashes"] = {name: digest.hexdigest() for name, digest in digests.items()}
    return result


def inspect_archive(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = InspectArchiveInput.model_validate(arguments)
    path = _require_file(context, values.path)
    if not zipfile.is_zipfile(path):
        raise ValueError(
            "inspect_archive currently requires a ZIP-compatible APK/JAR/AAB/APKS file"
        )
    query = values.name_query.casefold() if values.name_query else None
    entries: list[dict[str, Any]] = []
    names: Counter[str] = Counter()
    total_uncompressed = 0
    total_compressed = 0
    encrypted = 0
    unsafe = 0
    scanned = 0
    matched = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            scanned += 1
            names[info.filename] += 1
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
            is_encrypted = bool(info.flag_bits & 0x1)
            is_unsafe = _unsafe_archive_name(info.filename)
            encrypted += int(is_encrypted)
            unsafe += int(is_unsafe)
            if query is not None and query not in info.filename.casefold():
                continue
            matched += 1
            if len(entries) >= values.max_entries:
                continue
            entries.append(
                {
                    "name": info.filename,
                    "directory": info.is_dir(),
                    "uncompressed_size": info.file_size,
                    "compressed_size": info.compress_size,
                    "compression": info.compress_type,
                    "crc32": f"{info.CRC:08x}",
                    "encrypted": is_encrypted,
                    "unsafe_path": is_unsafe,
                }
            )
    duplicate_names = [name for name, count in names.items() if count > 1]
    return {
        "path": values.path,
        "archive_type": "zip-compatible",
        "entries_scanned": scanned,
        "matching_entries": matched,
        "returned_entries": len(entries),
        "truncated": matched > len(entries),
        "query": values.name_query,
        "total_uncompressed_size": total_uncompressed,
        "total_compressed_size": total_compressed,
        "compression_ratio": round(total_uncompressed / max(1, total_compressed), 2),
        "encrypted_entries": encrypted,
        "unsafe_path_entries": unsafe,
        "duplicate_entry_names": duplicate_names[:100],
        "duplicate_names_truncated": len(duplicate_names) > 100,
        "entries": entries,
    }


def read_archive_entry(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReadArchiveEntryInput.model_validate(arguments)
    path = _require_file(context, values.path)
    if not zipfile.is_zipfile(path):
        raise ValueError("read_archive_entry requires a ZIP-compatible archive")
    with zipfile.ZipFile(path) as archive:
        matches = [info for info in archive.infolist() if info.filename == values.entry]
        if not matches:
            raise ValueError(f"Archive entry not found: {values.entry}")
        if len(matches) > 1:
            raise ValueError("Archive contains duplicate entries with that name; inspect it first")
        info = matches[0]
        if info.is_dir():
            raise ValueError("Archive entry is a directory")
        if info.flag_bits & 0x1:
            raise ValueError("Encrypted archive entries cannot be read without a password")
        with archive.open(info, "r") as handle:
            data = handle.read(values.max_bytes + 1)
    truncated = len(data) > values.max_bytes
    data = data[: values.max_bytes]
    binary = b"\x00" in data[:8192]
    return {
        "path": values.path,
        "entry": values.entry,
        "declared_size": info.file_size,
        "returned_bytes": len(data),
        "truncated": truncated or info.file_size > len(data),
        "binary": binary,
        "sha256_of_returned_bytes": hashlib.sha256(data).hexdigest(),
        "text_preview": None if binary else data.decode("utf-8", errors="replace"),
        "hex_preview": data[:512].hex(" ") if binary else None,
    }


def inspect_structured_data(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = StructuredDataInput.model_validate(arguments)
    path = _require_file(context, values.path)
    raw = _read_small_file(path, MAX_STRUCTURED_BYTES, "structured-data")
    selected_format = _structured_format(path, raw, values.format)
    if selected_format == "xml":
        root = SafeElementTree.fromstring(raw)
        tag_counts: Counter[str] = Counter()
        matches: list[dict[str, Any]] = []
        query = values.query.casefold() if values.query else None
        for element in root.iter():
            tag = _local_name(element.tag)
            tag_counts[tag] += 1
            if query and query not in tag.casefold():
                continue
            if len(matches) < values.max_nodes:
                matches.append(
                    {
                        "tag": tag,
                        "attributes": dict(list(element.attrib.items())[:20]),
                        "text": (element.text or "").strip()[:1000],
                    }
                )
        return {
            "path": values.path,
            "format": selected_format,
            "root_tag": _local_name(root.tag),
            "tag_counts": dict(tag_counts.most_common(100)),
            "query": values.query,
            "matches": matches if query else [],
            "returned_nodes": len(matches),
            "total_nodes": sum(tag_counts.values()),
        }
    if selected_format == "json":
        parsed: Any = json.loads(raw)
    elif selected_format == "yaml":
        parsed = yaml.load(raw.decode("utf-8", errors="strict"), Loader=_NoAliasSafeLoader)
    elif selected_format == "plist":
        parsed = plistlib.loads(raw)
    elif selected_format == "ini":
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(raw.decode("utf-8", errors="strict"))
        parsed = {section: dict(parser.items(section)) for section in parser.sections()}
    else:  # pragma: no cover - guarded by _structured_format
        raise ValueError(f"Unsupported structured format: {selected_format}")
    selected = _query_value(parsed, values.query) if values.query else parsed
    bounded, visited, truncated = _bounded_structure(selected, values.max_nodes)
    return {
        "path": values.path,
        "format": selected_format,
        "query": values.query,
        "root_type": type(parsed).__name__,
        "returned_nodes": visited,
        "truncated": truncated,
        "value": bounded,
    }


def inspect_sqlite(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SqliteInput.model_validate(arguments)
    path = _require_file(context, values.path)
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise ValueError("The file does not have a SQLite 3 header")
    deadline = _deadline(context)
    uri = path.as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        tables = _sqlite_tables(connection)
        if values.table and values.table not in tables:
            raise ValueError(f"Unknown table: {values.table}")
        if values.action == "schema":
            records = []
            for table in tables[:100]:
                columns = connection.execute(
                    f"PRAGMA table_xinfo({_quote_identifier(table)})"
                ).fetchall()
                records.append(
                    {
                        "table": table,
                        "columns": [
                            {
                                "name": row["name"],
                                "type": row["type"],
                                "not_null": bool(row["notnull"]),
                                "primary_key": bool(row["pk"]),
                                "hidden": bool(row["hidden"]),
                            }
                            for row in columns[:200]
                        ],
                    }
                )
            indexes = [
                dict(row)
                for row in connection.execute(
                    "SELECT name, tbl_name AS table_name FROM sqlite_master "
                    "WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 200"
                )
            ]
            return {
                "path": values.path,
                "mode": "read-only immutable",
                "tables": records,
                "table_count": len(tables),
                "tables_truncated": len(tables) > 100,
                "indexes": indexes,
            }
        if values.action == "sample":
            assert values.table is not None
            rows = connection.execute(
                f"SELECT * FROM {_quote_identifier(values.table)} LIMIT ?", (values.limit,)
            ).fetchall()
            return {
                "path": values.path,
                "mode": "read-only immutable",
                "table": values.table,
                "rows": [_sqlite_row(row) for row in rows],
                "returned_rows": len(rows),
            }
        assert values.query is not None
        selected_tables = [values.table] if values.table else tables
        matches: list[dict[str, Any]] = []
        scan_complete = True
        for table in selected_tables:
            if time.monotonic() >= deadline or len(matches) >= values.limit:
                scan_complete = False
                break
            assert table is not None
            columns = connection.execute(
                f"PRAGMA table_xinfo({_quote_identifier(table)})"
            ).fetchall()
            searchable = [str(row["name"]) for row in columns if not bool(row["hidden"])][:50]
            if not searchable:
                continue
            predicates = " OR ".join(
                f"instr(lower(CAST({_quote_identifier(column)} AS TEXT)), lower(?)) > 0"
                for column in searchable
            )
            remaining = values.limit - len(matches)
            try:
                rows = connection.execute(
                    f"SELECT * FROM {_quote_identifier(table)} WHERE {predicates} LIMIT ?",
                    (*([values.query] * len(searchable)), remaining),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    scan_complete = False
                    break
                raise
            matches.extend({"table": table, "row": _sqlite_row(row)} for row in rows)
        return {
            "path": values.path,
            "mode": "read-only immutable",
            "query": values.query,
            "tables_considered": len(selected_tables),
            "returned_matches": len(matches),
            "scan_complete": scan_complete,
            "matches": matches,
        }
    finally:
        connection.close()


def summarize_source_file(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SourceSummaryInput.model_validate(arguments)
    path = _require_file(context, values.path)
    with path.open("rb") as handle:
        sample = handle.read(8192)
    if b"\x00" in sample:
        raise ValueError(
            "summarize_source_file requires decoded text/source, not a binary container"
        )
    deadline = _deadline(context)
    imports: dict[str, int] = {}
    declarations: list[dict[str, Any]] = []
    signals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    declaration_seen: set[tuple[str, str, int]] = set()
    signal_seen: set[tuple[str, int, str]] = set()
    result_budget_reached = False
    bytes_scanned = 0
    line_count = 0
    current_line_length = 0
    last_byte = b""
    longest_line = 0
    complete = True
    with path.open("rb") as handle:
        while bytes_scanned < min(path.stat().st_size, values.max_scan_bytes):
            if time.monotonic() >= deadline:
                complete = False
                break
            raw = handle.read(min(65536, values.max_scan_bytes - bytes_scanned))
            if not raw:
                break
            block_start_line = line_count + 1
            text = raw.decode("utf-8", errors="replace")
            segments = text.split("\n")
            for segment_index, segment in enumerate(segments):
                length = len(segment) + (current_line_length if segment_index == 0 else 0)
                longest_line = max(longest_line, length)
                current_line_length = length
                if segment_index < len(segments) - 1:
                    current_line_length = 0
            line_count += text.count("\n")
            for pattern in IMPORT_PATTERNS:
                for match in pattern.finditer(text):
                    module = next((group for group in match.groups() if group), "")
                    if module and module not in imports:
                        if len(imports) < values.max_results:
                            imports[module] = block_start_line + text[: match.start()].count("\n")
                        else:
                            result_budget_reached = True
            for kind, pattern in DECLARATION_PATTERNS:
                for match in pattern.finditer(text):
                    name = match.group(1)
                    line = block_start_line + text[: match.start()].count("\n")
                    key = (kind, name, line)
                    if key in declaration_seen or len(declarations) >= values.max_results:
                        if key not in declaration_seen and len(declarations) >= values.max_results:
                            result_budget_reached = True
                        continue
                    declaration_seen.add(key)
                    declarations.append({"kind": kind, "name": name, "line": line})
            for category, pattern in HIGH_SIGNAL_PATTERNS.items():
                for match in pattern.finditer(text):
                    line = block_start_line + text[: match.start()].count("\n")
                    preview = text[max(0, match.start() - 120) : match.end() + 180].replace(
                        "\n", " "
                    )
                    signal_key = (category, line, match.group(0))
                    if signal_key in signal_seen or len(signals[category]) >= values.max_results:
                        if (
                            signal_key not in signal_seen
                            and len(signals[category]) >= values.max_results
                        ):
                            result_budget_reached = True
                        continue
                    signal_seen.add(signal_key)
                    signals[category].append(
                        {"line": line, "match": match.group(0), "preview": preview[:500]}
                    )
            bytes_scanned += len(raw)
            last_byte = raw[-1:]
    size = path.stat().st_size
    if bytes_scanned < size:
        complete = False
    total_lines = line_count + int(bool(bytes_scanned and last_byte != b"\n"))
    return {
        "path": values.path,
        "language": LANGUAGES.get(path.suffix.lower(), "unknown"),
        "file_size": size,
        "bytes_scanned": bytes_scanned,
        "scan_complete": complete,
        "truncation_reason": None
        if complete
        else "time_budget"
        if bytes_scanned < min(size, values.max_scan_bytes)
        else "byte_budget",
        "line_count_in_scanned_region": total_lines,
        "longest_line_characters_in_scanned_region": longest_line,
        "likely_minified": longest_line >= 20000,
        "imports": [{"module": module, "line": line} for module, line in imports.items()],
        "declarations": declarations,
        "high_signal_calls": dict(signals),
        "results_truncated": result_budget_reached,
        "accuracy": "Source structure and calls are lexical triage leads, not a parsed call graph.",
    }


def map_source_dependencies(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = DependencyMapInput.model_validate(arguments)
    root = context.read_path(values.path)
    deadline = _deadline(context)
    module_files: dict[str, set[str]] = defaultdict(set)
    edges: list[dict[str, str]] = []
    scanned = 0
    prefix_truncated_files = 0
    complete = True
    for path in walk_regular_entries(root):
        if time.monotonic() >= deadline:
            complete = False
            break
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        scanned += 1
        if scanned > values.max_files:
            complete = False
            break
        try:
            with path.open("rb") as handle:
                raw = handle.read(values.max_bytes_per_file)
        except OSError:
            continue
        if path.stat().st_size > len(raw):
            prefix_truncated_files += 1
        if b"\x00" in raw[:8192]:
            continue
        display = _display_path(root, values.path, path)
        text = raw.decode("utf-8", errors="replace")
        for module in _extract_imports(text):
            module_files[module].add(display)
            if len(edges) < values.max_edges:
                edges.append({"source": display, "dependency": module})
    modules = [
        {"module": module, "file_count": len(files), "files": sorted(files)[:20]}
        for module, files in sorted(module_files.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    return {
        "path": values.path,
        "files_scanned": min(scanned, values.max_files),
        "files_scanned_by_prefix": prefix_truncated_files,
        "max_bytes_per_file": values.max_bytes_per_file,
        "scan_complete": complete,
        "module_count": len(modules),
        "edge_count": sum(len(files) for files in module_files.values()),
        "edges_truncated": sum(len(files) for files in module_files.values()) > len(edges),
        "modules": modules[:1000],
        "modules_truncated": len(modules) > 1000,
        "edges": edges,
        "accuracy": "Dependencies are extracted lexically from decoded source imports/includes.",
    }


def trace_symbol(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = TraceSymbolInput.model_validate(arguments)
    root = context.read_path(values.path)
    deadline = _deadline(context)
    symbol_pattern = re.compile(
        rf"(?<![\w$]){re.escape(values.symbol)}(?![\w$])",
        0 if values.case_sensitive else re.IGNORECASE,
    )
    records: list[dict[str, Any]] = []
    scanned = 0
    complete = True
    candidates = [root] if root.is_file() else walk_regular_entries(root)
    for path in candidates:
        if time.monotonic() >= deadline or len(records) >= values.max_results:
            complete = False
            break
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES | {".txt", ".xml"}:
            continue
        scanned += 1
        if scanned > values.max_files:
            complete = False
            break
        remaining = values.max_results - len(records)
        try:
            _, matches, file_complete = search_text_file_lines(
                path,
                values.symbol,
                case_sensitive=values.case_sensitive,
                max_results=remaining,
                stop_after=remaining,
                deadline=deadline,
            )
        except OSError:
            continue
        complete = complete and file_complete
        for line, preview in matches:
            match = symbol_pattern.search(preview)
            if match is None:
                continue
            records.append(
                {
                    "path": _display_path(root, values.path, path),
                    "line": line,
                    "classification": _classify_symbol_context(preview, match),
                    "preview": preview[:1000],
                }
            )
            if len(records) >= values.max_results:
                complete = False
                break
    counts = Counter(record["classification"] for record in records)
    return {
        "path": values.path,
        "symbol": values.symbol,
        "files_scanned": min(scanned, values.max_files),
        "returned_occurrences": len(records),
        "classification_counts": dict(counts),
        "scan_complete": complete,
        "occurrences": records,
        "accuracy": "Definition/call/assignment labels are lexical and require source verification.",
    }


def compare_files(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = CompareFilesInput.model_validate(arguments)
    left = _require_file(context, values.left_path)
    right = _require_file(context, values.right_path)
    deadline = _deadline(context)
    left_hash = hashlib.sha256()
    right_hash = hashlib.sha256()
    first_difference: int | None = None
    offset = 0
    complete = True
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while True:
            if time.monotonic() >= deadline:
                complete = False
                break
            left_block = left_handle.read(1024 * 1024)
            right_block = right_handle.read(1024 * 1024)
            if not left_block and not right_block:
                break
            left_hash.update(left_block)
            right_hash.update(right_block)
            if first_difference is None and left_block != right_block:
                shared = min(len(left_block), len(right_block))
                local = next(
                    (index for index in range(shared) if left_block[index] != right_block[index]),
                    shared,
                )
                first_difference = offset + local
            offset += max(len(left_block), len(right_block))
    result: dict[str, Any] = {
        "left_path": values.left_path,
        "right_path": values.right_path,
        "left_size": left.stat().st_size,
        "right_size": right.stat().st_size,
        "comparison_complete": complete,
        "first_differing_offset": first_difference,
    }
    if complete:
        left_digest = left_hash.hexdigest()
        right_digest = right_hash.hexdigest()
        result.update(
            {
                "left_sha256": left_digest,
                "right_sha256": right_digest,
                "identical": left_digest == right_digest,
            }
        )
    small_text = (
        complete
        and left.stat().st_size <= 4 * 1024 * 1024
        and right.stat().st_size <= 4 * 1024 * 1024
        and not _binary_sample(left)
        and not _binary_sample(right)
    )
    if small_text and result.get("identical") is False:
        left_lines = left.read_text(encoding="utf-8", errors="replace").splitlines()
        right_lines = right.read_text(encoding="utf-8", errors="replace").splitlines()
        diff = list(
            itertools.islice(
                difflib.unified_diff(
                    left_lines,
                    right_lines,
                    fromfile=values.left_path,
                    tofile=values.right_path,
                    lineterm="",
                ),
                values.max_diff_lines + 1,
            )
        )
        result["diff"] = diff[: values.max_diff_lines]
        result["diff_truncated"] = len(diff) > values.max_diff_lines
    else:
        result["diff"] = []
        result["diff_truncated"] = False
        result["diff_note"] = "Text diff is limited to complete comparisons of files up to 4 MiB."
    return result


def decode_static_value(_: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = DecodeStaticInput.model_validate(arguments)
    source = _decode_input(values.value, values.input_encoding)
    candidates: list[dict[str, Any]] = []
    operations = (
        ("hex", "base64", "url", "rot13") if values.operation == "auto" else (values.operation,)
    )
    for operation in operations:
        try:
            if operation == "hex":
                decoded = bytes.fromhex(values.value.strip())
            elif operation == "base64":
                compact = re.sub(r"\s+", "", values.value)
                compact += "=" * (-len(compact) % 4)
                decoded = base64.b64decode(compact, altchars=b"-_", validate=True)
            elif operation == "url":
                decoded = unquote_to_bytes(values.value)
            elif operation == "rot13":
                decoded = codecs.decode(values.value, "rot_13").encode("utf-8")
            elif operation == "xor":
                assert values.xor_key is not None
                decoded = bytes(byte ^ values.xor_key for byte in source)
            else:  # pragma: no cover - validated literal
                continue
        except (ValueError, UnicodeError):
            if values.operation != "auto":
                raise ValueError(f"Input is not valid for {operation}") from None
            continue
        if operation in {"url", "rot13"} and decoded == source:
            continue
        candidates.append(_decoded_record(operation, decoded))
    if not candidates:
        raise ValueError("No valid static decoding was found for the selected operation")
    return {
        "operation": values.operation,
        "input_encoding": values.input_encoding,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "safety": "Decoded bytes were returned as data and were not executed.",
    }


def inspect_android_manifest(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ManifestInput.model_validate(arguments)
    path = _require_file(context, values.path)
    raw = _read_small_file(path, MAX_MANIFEST_BYTES, "Android manifest")
    if b"\x00" in raw[:1024]:
        raise ValueError(
            "This appears to be compiled binary AXML. Provide an already decoded manifest "
            "from a trusted static extraction tool."
        )
    try:
        root = SafeElementTree.fromstring(raw)
    except Exception as exc:
        raise ValueError(f"Could not parse decoded AndroidManifest XML: {exc}") from exc
    android = "{http://schemas.android.com/apk/res/android}"

    def attr(element: Any, name: str) -> str | None:
        return element.attrib.get(android + name) or element.attrib.get(name)

    permissions = sorted(
        name
        for element in root.findall("uses-permission")
        if (name := attr(element, "name")) is not None
    )
    features = sorted(
        name
        for element in root.findall("uses-feature")
        if (name := attr(element, "name")) is not None
    )
    sdk = root.find("uses-sdk")
    application = root.find("application")
    components: list[dict[str, Any]] = []
    component_count = 0
    risky: list[str] = []
    if application is not None:
        for kind in ("activity", "activity-alias", "service", "receiver", "provider"):
            for element in application.findall(kind):
                component_count += 1
                filters = []
                for intent_filter in element.findall("intent-filter"):
                    filters.append(
                        {
                            "actions": [
                                attr(item, "name") for item in intent_filter.findall("action")
                            ],
                            "categories": [
                                attr(item, "name") for item in intent_filter.findall("category")
                            ],
                            "data": [
                                {
                                    key: attr(item, key)
                                    for key in (
                                        "scheme",
                                        "host",
                                        "port",
                                        "path",
                                        "pathPrefix",
                                        "mimeType",
                                    )
                                    if attr(item, key) is not None
                                }
                                for item in intent_filter.findall("data")
                            ],
                        }
                    )
                exported = attr(element, "exported")
                record = {
                    "type": kind,
                    "name": attr(element, "name"),
                    "exported": exported,
                    "enabled": attr(element, "enabled"),
                    "permission": attr(element, "permission"),
                    "process": attr(element, "process"),
                    "intent_filters": filters,
                    "implicit_export_candidate": exported is None and bool(filters),
                }
                if len(components) < values.max_components:
                    components.append(record)
                if (exported == "true" or record["implicit_export_candidate"]) and not record[
                    "permission"
                ]:
                    risky.append(f"{kind} {record['name']} may be exported without a permission")
    application_flags = (
        {
            name: attr(application, name)
            for name in (
                "debuggable",
                "allowBackup",
                "usesCleartextTraffic",
                "networkSecurityConfig",
                "extractNativeLibs",
                "requestLegacyExternalStorage",
            )
        }
        if application is not None
        else {}
    )
    if application_flags.get("debuggable") == "true":
        risky.append("Application is explicitly debuggable")
    if application_flags.get("allowBackup") == "true":
        risky.append("Application explicitly allows backup")
    if application_flags.get("usesCleartextTraffic") == "true":
        risky.append("Application explicitly allows cleartext traffic")
    return {
        "path": values.path,
        "package": root.attrib.get("package"),
        "version_code": attr(root, "versionCode"),
        "version_name": attr(root, "versionName"),
        "sdk": {
            "min": attr(sdk, "minSdkVersion") if sdk is not None else None,
            "target": attr(sdk, "targetSdkVersion") if sdk is not None else None,
            "max": attr(sdk, "maxSdkVersion") if sdk is not None else None,
        },
        "permissions": permissions,
        "features": features,
        "application_flags": application_flags,
        "components": components,
        "component_count": component_count,
        "components_truncated": component_count > len(components),
        "security_observations": risky[:200],
        "accuracy": "Observations describe static declarations and do not prove runtime reachability.",
    }


def inspect_source_map(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SourceMapInput.model_validate(arguments)
    path = _require_file(context, values.path)
    raw = _read_small_file(path, MAX_SOURCE_MAP_BYTES, "source map")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sources"), list):
        raise ValueError("The file is not a standard source-map object with a sources array")
    sources = [str(item) for item in parsed["sources"]]
    contents = parsed.get("sourcesContent")
    content_list = contents if isinstance(contents, list) else []
    query = values.source_query.casefold() if values.source_query else None
    records: list[dict[str, Any]] = []
    embedded_count = 0
    embedded_bytes = 0
    for index, source in enumerate(sources):
        content = content_list[index] if index < len(content_list) else None
        if isinstance(content, str):
            embedded_count += 1
            embedded_bytes += len(content.encode("utf-8", errors="replace"))
        if query and query not in source.casefold():
            continue
        if len(records) >= values.max_sources:
            continue
        record: dict[str, Any] = {
            "index": index,
            "source": source,
            "embedded": isinstance(content, str),
            "embedded_characters": len(content) if isinstance(content, str) else 0,
        }
        if values.include_content and isinstance(content, str):
            record["content_preview"] = content[:4000]
            record["content_truncated"] = len(content) > 4000
        records.append(record)
    matched_count = sum(1 for source in sources if not query or query in source.casefold())
    suspicious = [
        source
        for source in sources
        if source.startswith(("/", "\\")) or ".." in PurePosixPath(source).parts
    ]
    return {
        "path": values.path,
        "version": parsed.get("version"),
        "generated_file": parsed.get("file"),
        "source_root": parsed.get("sourceRoot"),
        "source_count": len(sources),
        "name_count": len(parsed.get("names", [])) if isinstance(parsed.get("names"), list) else 0,
        "mappings_characters": len(parsed.get("mappings", "")),
        "embedded_source_count": embedded_count,
        "embedded_source_bytes": embedded_bytes,
        "source_query": values.source_query,
        "matching_sources": matched_count,
        "returned_sources": len(records),
        "truncated": matched_count > len(records),
        "suspicious_source_paths": suspicious[:100],
        "sources": records,
    }


def register_research_tools(registry: ToolRegistry) -> None:
    definitions: list[tuple[str, str, type[BaseModel], ToolHandler]] = [
        (
            "inspect_file",
            "Identify file magic, encoding, hashes, entropy, and byte-level characteristics in one pass.",
            InspectFileInput,
            inspect_file,
        ),
        (
            "inspect_archive",
            "Inventory ZIP/APK/JAR/AAB/APKS entries, sizes, encryption, duplicates, and unsafe paths without extraction.",
            InspectArchiveInput,
            inspect_archive,
        ),
        (
            "read_archive_entry",
            "Read a bounded ZIP/APK/JAR/AAB entry in memory without extracting or executing it.",
            ReadArchiveEntryInput,
            read_archive_entry,
        ),
        (
            "inspect_structured_data",
            "Safely inspect bounded JSON, YAML, plist, XML, or INI data with an optional query.",
            StructuredDataInput,
            inspect_structured_data,
        ),
        (
            "inspect_sqlite",
            "Inspect SQLite schemas, samples, or text matches through immutable read-only queries.",
            SqliteInput,
            inspect_sqlite,
        ),
        (
            "summarize_source_file",
            "Scan a large decoded source file once for language, imports, declarations, minification, and high-signal calls.",
            SourceSummaryInput,
            summarize_source_file,
        ),
        (
            "map_source_dependencies",
            "Build a bounded cross-file import/include dependency map for decoded source trees.",
            DependencyMapInput,
            map_source_dependencies,
        ),
        (
            "trace_symbol",
            "Trace a symbol across large source trees and classify definitions, calls, assignments, and references.",
            TraceSymbolInput,
            trace_symbol,
        ),
        (
            "compare_files",
            "Compare two case files by size, SHA-256, first differing offset, and bounded text diff.",
            CompareFilesInput,
            compare_files,
        ),
        (
            "decode_static_value",
            "Decode bounded hex, Base64, URL, ROT13, or single-byte XOR data without executing it.",
            DecodeStaticInput,
            decode_static_value,
        ),
        (
            "inspect_android_manifest",
            "Summarize a decoded AndroidManifest.xml, permissions, components, intent filters, and risky declarations.",
            ManifestInput,
            inspect_android_manifest,
        ),
        (
            "inspect_source_map",
            "Inspect JavaScript source-map metadata and bounded embedded-source previews.",
            SourceMapInput,
            inspect_source_map,
        ),
    ]
    for name, description, model, handler in definitions:
        registry.register(ToolDefinition(name, "core", description, model, handler))


def _require_file(context: ToolContext, requested: str) -> Path:
    path = context.read_path(requested)
    if not path.is_file():
        raise ValueError("A regular file is required")
    return path


def _deadline(context: ToolContext) -> float:
    return time.monotonic() + context.config.limits.command_timeout_seconds


def _detect_encoding(sample: bytes) -> str:
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    if sample.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if not sample:
        return "empty"
    if b"\x00" in sample:
        even_nulls = sample[0::2].count(0)
        odd_nulls = sample[1::2].count(0)
        if max(even_nulls, odd_nulls) > len(sample) // 8:
            return "probable-utf-16"
        return "binary"
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return "unknown-8-bit-or-binary"
    return "ascii" if all(byte < 128 for byte in sample) else "utf-8"


def _unsafe_archive_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        normalized.startswith("/")
        or ".." in path.parts
        or bool(re.match(r"^[A-Za-z]:", normalized))
    )


def _read_small_file(path: Path, maximum: int, label: str) -> bytes:
    size = path.stat().st_size
    if size > maximum:
        raise ValueError(
            f"{label} parsing is limited to {maximum} bytes; use bounded search or large-text indexing"
        )
    with path.open("rb") as handle:
        return handle.read(maximum + 1)


def _structured_format(path: Path, raw: bytes, requested: StructuredFormat) -> str:
    if requested != "auto":
        return requested
    suffix = path.suffix.lower()
    by_suffix = {
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".plist": "plist",
        ".xml": "xml",
        ".ini": "ini",
        ".cfg": "ini",
    }
    if suffix in by_suffix:
        return by_suffix[suffix]
    stripped = raw.lstrip()
    if stripped.startswith((b"{", b"[")):
        return "json"
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<"):
        return "xml"
    if raw.startswith(b"bplist"):
        return "plist"
    raise ValueError("Could not determine structured format; specify format explicitly")


def _local_name(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _query_value(value: Any, query: str | None) -> Any:
    if not query:
        return value
    current = value
    parts = [part for part in re.split(r"\.|\[|\]", query) if part]
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"Structured query key not found: {part}")
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise ValueError(f"Structured query index out of range: {index}")
            current = current[index]
        else:
            raise ValueError(f"Cannot descend through structured query part: {part}")
    return current


def _bounded_structure(value: Any, maximum: int) -> tuple[Any, int, bool]:
    state = {"visited": 0, "truncated": False}

    def visit(item: Any, depth: int) -> Any:
        if state["visited"] >= maximum or depth >= 20:
            state["truncated"] = True
            return "<truncated>"
        state["visited"] += 1
        if isinstance(item, dict):
            object_result: dict[str, Any] = {}
            for key, child in item.items():
                if state["visited"] >= maximum:
                    state["truncated"] = True
                    break
                object_result[str(key)[:500]] = visit(child, depth + 1)
            return object_result
        if isinstance(item, (list, tuple)):
            list_result: list[Any] = []
            for child in item:
                if state["visited"] >= maximum:
                    state["truncated"] = True
                    break
                list_result.append(visit(child, depth + 1))
            return list_result
        if isinstance(item, bytes):
            return {"bytes": len(item), "hex_preview": item[:256].hex()}
        if isinstance(item, str):
            return item[:4000] + ("…" if len(item) > 4000 else "")
        return item

    bounded = visit(value, 0)
    return bounded, int(state["visited"]), bool(state["truncated"])


def _sqlite_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_row(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = {}
    keys = row.keys()
    for key in keys:
        value = row[key]
        if isinstance(value, bytes):
            result[key] = {
                "type": "blob",
                "length": len(value),
                "hex_preview": value[:256].hex(),
            }
        elif isinstance(value, str) and len(value) > 4000:
            result[key] = value[:4000] + "…"
        else:
            result[key] = value
    return result


def _extract_imports(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in IMPORT_PATTERNS:
        for match in pattern.finditer(text):
            module = next((group for group in match.groups() if group), "")
            if module and module not in seen:
                seen.add(module)
                found.append(module)
    return found


def _display_path(root: Path, requested: str, path: Path) -> str:
    if root.is_file():
        return requested
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return relative if requested == "." else (Path(requested) / relative).as_posix()


def _classify_symbol_context(preview: str, match: re.Match[str]) -> str:
    before = preview[: match.start()]
    after = preview[match.end() :]
    if re.search(r"(?:class|interface|object|enum|function|fun|def|\.method)\s+$", before):
        return "definition"
    if re.match(r"\s*\(", after):
        return "call_or_declaration"
    if re.match(r"\s*(?::[^=]+)?=", after):
        return "assignment"
    return "reference"


def _binary_sample(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\x00" in handle.read(8192)


def _decode_input(value: str, encoding: str) -> bytes:
    if encoding == "text":
        return value.encode("utf-8")
    if encoding == "hex":
        try:
            return bytes.fromhex(value)
        except ValueError:
            raise ValueError("value is not valid hexadecimal input") from None
    compact = re.sub(r"\s+", "", value)
    compact += "=" * (-len(compact) % 4)
    try:
        return base64.b64decode(compact, altchars=b"-_", validate=True)
    except ValueError:
        raise ValueError("value is not valid Base64 input") from None


def _decoded_record(operation: str, decoded: bytes) -> dict[str, Any]:
    limited = decoded[:32768]
    return {
        "operation": operation,
        "decoded_bytes": len(decoded),
        "truncated": len(decoded) > len(limited),
        "utf8_preview": limited.decode("utf-8", errors="replace"),
        "hex_preview": limited[:512].hex(" "),
        "sha256": hashlib.sha256(decoded).hexdigest(),
    }
