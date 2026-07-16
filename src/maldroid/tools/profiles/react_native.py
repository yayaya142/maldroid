"""Focused, bounded React Native and Metro bundle tools."""

from __future__ import annotations

import bisect
import hashlib
import json
import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from maldroid.exceptions import CaseError
from maldroid.io_utils import atomic_write_json
from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry

METRO_MARKER = re.compile(rb"(?:^|[^\w$])__d\s*\(")
MODULE_ID_TAIL = re.compile(rb"\}\s*,\s*(\d+)\s*,\s*\[")
URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BundleInput(Arguments):
    path: str


class IndexBundleInput(BundleInput):
    pass


class ListModulesInput(BundleInput):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class ReadModuleInput(BundleInput):
    module: str
    max_characters: int = Field(default=16000, ge=1000, le=50000)


class SearchBundleInput(BundleInput):
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=50, ge=1, le=200)
    context_characters: int = Field(default=160, ge=20, le=1000)


class TriageBundleInput(BundleInput):
    max_results_per_family: int = Field(default=25, ge=1, le=200)


RN_BEHAVIOR_PATTERNS: dict[str, re.Pattern[bytes]] = {
    "network": re.compile(rb"https?://|wss?://|\bfetch\b|axios|XMLHttpRequest|WebSocket", re.I),
    "storage": re.compile(rb"AsyncStorage|MMKV|SQLite|Realm|Keychain|EncryptedStorage", re.I),
    "native_bridge": re.compile(
        rb"NativeModules|TurboModuleRegistry|requireNativeComponent|DeviceEventEmitter", re.I
    ),
    "dynamic_code": re.compile(
        rb"\beval\s*\(|new\s+Function|dynamic\s+import|sourceMappingURL", re.I
    ),
    "identifiers": re.compile(
        rb"ANDROID_ID|advertisingId|deviceId|installationId|getImei|getSubscriberId", re.I
    ),
    "android_capability": re.compile(
        rb"AccessibilityService|DeviceAdmin|NotificationListener|VpnService|SYSTEM_ALERT_WINDOW|BOOT_COMPLETED",
        re.I,
    ),
    "crypto_encoding": re.compile(rb"AES|RSA|Hmac|SHA-?256|encrypt|decrypt|base64", re.I),
    "command_channel": re.compile(
        rb"command|opcode|dispatch|handler|heartbeat|polling|pushToken|onMessage", re.I
    ),
}

BRIDGE_PATTERNS = (
    re.compile(rb"NativeModules\.([A-Za-z_$][\w$]{1,127})"),
    re.compile(rb"TurboModuleRegistry\.(?:get|getEnforcing)\([\"']([^\"']{1,128})"),
    re.compile(rb"requireNativeComponent\([\"']([^\"']{1,128})"),
)


def inspect_javascript_bundle(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = BundleInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file():
        raise ValueError("A JavaScript bundle file is required.")
    size = path.stat().st_size
    with path.open("rb") as handle:
        first = handle.read(min(size, 256 * 1024))
        tail_start = max(len(first), size - 256 * 1024)
        handle.seek(tail_start)
        last = handle.read(256 * 1024)
    sample = (first + b"\n" + last).decode("utf-8", errors="replace")
    line_count, longest_line, total_line_bytes = _stream_line_metrics(path)
    average = total_line_bytes / max(line_count, 1)
    metro_count_sample = len(METRO_MARKER.findall(first)) + len(METRO_MARKER.findall(last))
    return {
        "path": values.path,
        "size": size,
        "line_count": line_count,
        "appears_binary": b"\x00" in first,
        "appears_minified": average > 500 or longest_line > 10000,
        "average_line_bytes": round(average, 2),
        "longest_line_bytes": longest_line,
        "metro_wrapper_indicators": metro_count_sample,
        "appears_metro": metro_count_sample > 0 or "__r(" in sample,
        "source_map_reference": "sourceMappingURL=" in sample,
        "hermes_text_indicators": [
            indicator for indicator in ("HermesInternal", "hermes") if indicator in sample
        ],
        "parsing_note": "All format conclusions are heuristic until a module index is built.",
    }


def index_metro_bundle(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = IndexBundleInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file():
        raise ValueError("A Metro bundle file is required.")
    offsets = _find_marker_offsets(path)
    if not offsets:
        raise CaseError("No Metro __d module wrappers were found. The format may be unsupported.")
    offsets.append(path.stat().st_size)
    lines = _line_numbers_for_offsets(path, offsets[:-1])
    modules: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for ordinal, (start, end) in enumerate(zip(offsets, offsets[1:], strict=False), 1):
            tail_start = max(start, end - 8192)
            handle.seek(tail_start)
            tail = handle.read(end - tail_start)
            identifiers = MODULE_ID_TAIL.findall(tail)
            module_id = identifiers[-1].decode() if identifiers else f"ordinal-{ordinal}"
            modules.append(
                {
                    "module": module_id,
                    "ordinal": ordinal,
                    "start_offset": start,
                    "end_offset": end,
                    "start_line": lines[ordinal - 1],
                    "size": end - start,
                    "id_certainty": "parsed-tail" if identifiers else "ordinal-only",
                }
            )
    payload = {
        "schema_version": 1,
        "path": values.path,
        "source_path": str(path),
        "size": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
        "sha256": _sha256(path),
        "parsing": "heuristic-metro-wrapper-boundaries",
        "modules": modules,
    }
    target = _index_path(context, values.path)
    atomic_write_json(target, payload)
    return {
        "path": values.path,
        "module_count": len(modules),
        "index_file": target.relative_to(context.case.root).as_posix(),
        "parsing": payload["parsing"],
    }


def list_bundle_modules(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ListModulesInput.model_validate(arguments)
    index = _load_index(context, values.path)
    modules = index["modules"]
    start = (values.page - 1) * values.page_size
    selected = modules[start : start + values.page_size]
    return {
        "path": values.path,
        "total_modules": len(modules),
        "page": values.page,
        "returned_modules": len(selected),
        "truncated": start + len(selected) < len(modules),
        "modules": selected,
    }


def read_bundle_module(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReadModuleInput.model_validate(arguments)
    index = _load_index(context, values.path)
    module = next(
        (
            item
            for item in index["modules"]
            if str(item["module"]) == values.module or str(item["ordinal"]) == values.module
        ),
        None,
    )
    if not module:
        raise CaseError(f"Bundle module not found: {values.module}")
    path = context.read_path(values.path)
    with path.open("rb") as handle:
        handle.seek(module["start_offset"])
        raw = handle.read(min(module["size"], values.max_characters + 1))
    text = raw.decode("utf-8", errors="replace")
    return {
        **module,
        "path": values.path,
        "content": text[: values.max_characters],
        "truncated": module["size"] > values.max_characters,
    }


def search_bundle_modules(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchBundleInput.model_validate(arguments)
    return _search_bundle(context, values)


def find_javascript_symbol(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchBundleInput.model_validate(arguments)
    return _search_bundle(context, values) | {"symbol": values.query, "matching": "exact text"}


def trace_javascript_symbol_occurrences(
    context: ToolContext, arguments: BaseModel
) -> dict[str, Any]:
    values = SearchBundleInput.model_validate(arguments)
    return _search_bundle(context, values) | {
        "symbol": values.query,
        "note": "Occurrences are evidence locations, not a reconstructed runtime call graph.",
    }


def extract_bundle_urls(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = BundleInput.model_validate(arguments)
    path = context.read_path(values.path)
    found: dict[str, int] = {}
    carry = ""
    line_number = 1
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            text = carry + block.decode("utf-8", errors="replace")
            for match in URL.finditer(text):
                url = match.group(0).rstrip(".,);]")
                approximate_line = line_number + text[: match.start()].count("\n")
                found.setdefault(url, approximate_line)
            line_number += text[:-2048].count("\n") if len(text) > 2048 else 0
            carry = text[-2048:]
    results = [{"url": url, "line": line} for url, line in sorted(found.items())]
    return {"path": values.path, "total_urls": len(results), "results": results}


def triage_react_native_bundle(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = TriageBundleInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file():
        raise ValueError("A React Native bundle file is required.")
    modules: list[dict[str, Any]] = []
    with suppress(CaseError):
        modules = _load_index(context, values.path)["modules"]
    starts = [item["start_offset"] for item in modules]
    totals = {family: 0 for family in RN_BEHAVIOR_PATTERNS}
    results: dict[str, list[dict[str, Any]]] = {family: [] for family in RN_BEHAVIOR_PATTERNS}
    carry = b""
    consumed = 0
    line = 1
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            data = carry + block
            base = consumed - len(carry)
            safe_length = max(0, len(data) - 4096)
            searchable = data[:safe_length] if block else data
            for family, pattern in RN_BEHAVIOR_PATTERNS.items():
                for match in pattern.finditer(searchable):
                    totals[family] += 1
                    if len(results[family]) >= values.max_results_per_family:
                        continue
                    absolute = base + match.start()
                    module = None
                    if starts:
                        module_index = max(0, bisect.bisect_right(starts, absolute) - 1)
                        module = modules[module_index]["module"]
                    preview_start = max(0, match.start() - 100)
                    preview_end = min(len(data), match.end() + 100)
                    results[family].append(
                        {
                            "match": match.group(0).decode("utf-8", errors="replace"),
                            "offset": absolute,
                            "line": line + data[: match.start()].count(b"\n"),
                            "module": module,
                            "preview": data[preview_start:preview_end].decode(
                                "utf-8", errors="replace"
                            ),
                        }
                    )
            line += searchable.count(b"\n")
            consumed += len(block)
            carry = data[safe_length:]
    final_base = consumed - len(carry)
    for family, pattern in RN_BEHAVIOR_PATTERNS.items():
        for match in pattern.finditer(carry):
            totals[family] += 1
            if len(results[family]) >= values.max_results_per_family:
                continue
            absolute = final_base + match.start()
            module = None
            if starts:
                module_index = max(0, bisect.bisect_right(starts, absolute) - 1)
                module = modules[module_index]["module"]
            results[family].append(
                {
                    "match": match.group(0).decode("utf-8", errors="replace"),
                    "offset": absolute,
                    "line": line + carry[: match.start()].count(b"\n"),
                    "module": module,
                    "preview": carry[max(0, match.start() - 100) : match.end() + 100].decode(
                        "utf-8", errors="replace"
                    ),
                }
            )
    return {
        "path": values.path,
        "metro_index_used": bool(modules),
        "totals": totals,
        "results": results,
        "truncated_families": [
            family for family, total in totals.items() if total > values.max_results_per_family
        ],
        "accuracy": "Matches prioritize investigation paths; verify reachability and data flow.",
    }


def list_react_native_bridges(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = BundleInput.model_validate(arguments)
    path = context.read_path(values.path)
    names: dict[str, set[int]] = {}
    carry = b""
    consumed = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            data = carry + block
            base = consumed - len(carry)
            for pattern in BRIDGE_PATTERNS:
                for match in pattern.finditer(data):
                    name = match.group(1).decode("utf-8", errors="replace")
                    names.setdefault(name, set()).add(base + match.start())
            consumed += len(block)
            carry = data[-512:]
    records = [
        {"name": name, "occurrences": len(offsets), "sample_offsets": sorted(offsets)[:10]}
        for name, offsets in sorted(names.items())
    ]
    return {
        "path": values.path,
        "total_bridges": len(records),
        "bridges": records[:500],
        "truncated": len(records) > 500,
        "next_step": "Correlate names with Java/Kotlin native modules and inspect call sites.",
    }


def register_react_native_tools(registry: ToolRegistry) -> None:
    definitions: list[tuple[str, str, type[BaseModel], ToolHandler]] = [
        (
            "inspect_javascript_bundle",
            "Inspect bounded JavaScript and Metro bundle characteristics.",
            BundleInput,
            inspect_javascript_bundle,
        ),
        (
            "index_metro_bundle",
            "Heuristically index Metro module wrapper boundaries.",
            IndexBundleInput,
            index_metro_bundle,
        ),
        (
            "list_bundle_modules",
            "List bounded module metadata from a Metro index.",
            ListModulesInput,
            list_bundle_modules,
        ),
        (
            "search_bundle_modules",
            "Search exact text and map occurrences to indexed modules.",
            SearchBundleInput,
            search_bundle_modules,
        ),
        (
            "read_bundle_module",
            "Read one bounded indexed Metro module.",
            ReadModuleInput,
            read_bundle_module,
        ),
        (
            "find_javascript_symbol",
            "Find exact JavaScript symbol text without reading the full bundle.",
            SearchBundleInput,
            find_javascript_symbol,
        ),
        (
            "trace_javascript_symbol_occurrences",
            "Trace bounded symbol occurrences and evidence contexts.",
            SearchBundleInput,
            trace_javascript_symbol_occurrences,
        ),
        (
            "extract_bundle_urls",
            "Extract URLs from a bundle without adding the bundle to model context.",
            BundleInput,
            extract_bundle_urls,
        ),
        (
            "triage_react_native_bundle",
            "Map high-signal behavior families to bounded bundle offsets and Metro modules.",
            TriageBundleInput,
            triage_react_native_bundle,
        ),
        (
            "list_react_native_bridges",
            "Inventory NativeModules, TurboModules, and native components with offsets.",
            BundleInput,
            list_react_native_bridges,
        ),
    ]
    for name, description, model, handler in definitions:
        registry.register(ToolDefinition(name, "react-native", description, model, handler))


def _index_path(context: ToolContext, case_path: str) -> Path:
    digest = hashlib.sha256(case_path.encode()).hexdigest()[:16]
    directory = context.case.internal / "indexes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"react-native-{digest}.json"


def _load_index(context: ToolContext, case_path: str) -> dict[str, Any]:
    target = _index_path(context, case_path)
    if not target.is_file():
        raise CaseError("No Metro index exists. Run index_metro_bundle first.")
    index = json.loads(target.read_text(encoding="utf-8"))
    source = context.read_path(case_path)
    stat = source.stat()
    if stat.st_size != index["size"] or stat.st_mtime_ns != index["mtime_ns"]:
        raise CaseError("The bundle changed after indexing. Rebuild the Metro index.")
    return index


def _find_marker_offsets(path: Path) -> list[int]:
    offsets: list[int] = []
    carry = b""
    consumed = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            data = carry + block
            base = consumed - len(carry)
            for match in METRO_MARKER.finditer(data):
                marker = base + match.start()
                if match.group(0)[:1] not in {b"_", b""}:
                    marker += 1
                if marker >= 0 and (not offsets or marker > offsets[-1]):
                    offsets.append(marker)
            consumed += len(block)
            carry = data[-128:]
    return offsets


def _line_numbers_for_offsets(path: Path, offsets: list[int]) -> list[int]:
    results: list[int] = []
    target_index = 0
    line = 1
    position = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            while target_index < len(offsets) and offsets[target_index] < position + len(block):
                local = offsets[target_index] - position
                results.append(line + block[:local].count(b"\n"))
                target_index += 1
            line += block.count(b"\n")
            position += len(block)
    return results


def _search_bundle(context: ToolContext, values: SearchBundleInput) -> dict[str, Any]:
    index = _load_index(context, values.path)
    path = context.read_path(values.path)
    needle = values.query.encode("utf-8")
    starts = [item["start_offset"] for item in index["modules"]]
    results: list[dict[str, Any]] = []
    carry = b""
    consumed = 0
    line = 1
    last_emitted_offset = -1
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            data = carry + block
            base = consumed - len(carry)
            search_from = 0
            while len(results) < values.max_results:
                local = data.find(needle, search_from)
                if local < 0:
                    break
                absolute = base + local
                if absolute <= last_emitted_offset:
                    search_from = local + max(1, len(needle))
                    continue
                module_index = max(0, bisect.bisect_right(starts, absolute) - 1)
                start = max(0, local - values.context_characters)
                end = min(len(data), local + len(needle) + values.context_characters)
                approximate_line = line + data[:local].count(b"\n")
                results.append(
                    {
                        "module": index["modules"][module_index]["module"],
                        "offset": absolute,
                        "line": approximate_line,
                        "preview": data[start:end].decode("utf-8", errors="replace"),
                    }
                )
                last_emitted_offset = absolute
                search_from = local + max(1, len(needle))
            consumed += len(block)
            safe = max(0, len(data) - max(len(needle), values.context_characters) - 1)
            line += data[:safe].count(b"\n")
            carry = data[safe:]
            if len(results) >= values.max_results:
                break
    return {
        "path": values.path,
        "query": values.query,
        "returned_matches": len(results),
        "limit": values.max_results,
        "truncated": len(results) >= values.max_results,
        "results": results,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stream_line_metrics(path: Path) -> tuple[int, int, int]:
    """Count line lengths in fixed-size blocks, including newline bytes like file iteration."""
    line_count = 0
    longest_line = 0
    current_line_bytes = 0
    total_bytes = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total_bytes += len(block)
            segments = block.split(b"\n")
            if len(segments) == 1:
                current_line_bytes += len(block)
                continue
            first_length = current_line_bytes + len(segments[0]) + 1
            line_count += 1
            longest_line = max(longest_line, first_length)
            for segment in segments[1:-1]:
                length = len(segment) + 1
                line_count += 1
                longest_line = max(longest_line, length)
            current_line_bytes = len(segments[-1])
    if current_line_bytes:
        line_count += 1
        longest_line = max(longest_line, current_line_bytes)
    return line_count, longest_line, total_bytes
