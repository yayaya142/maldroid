"""High-signal static triage tools for very large evidence sets."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from maldroid.io_utils import atomic_write_json, atomic_write_text
from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryInput(Arguments):
    path: str = "."
    max_files: int = Field(default=20000, ge=1, le=100000)
    largest_count: int = Field(default=25, ge=1, le=100)


class NetworkIndicatorInput(Arguments):
    path: str = "."
    max_files: int = Field(default=10000, ge=1, le=50000)
    max_results: int = Field(default=500, ge=1, le=5000)


BehaviorCategory = Literal[
    "network",
    "persistence",
    "identifiers",
    "crypto",
    "dynamic_code",
    "native_bridge",
    "commands",
    "webview",
]


class BehaviorSearchInput(Arguments):
    path: str = "."
    categories: list[BehaviorCategory] = Field(default_factory=list, max_length=8)
    max_results_per_category: int = Field(default=50, ge=1, le=500)


class ByteRangeInput(Arguments):
    path: str
    start_offset: int = Field(default=0, ge=0)
    length: int = Field(default=4096, ge=1, le=65536)


class ReportInput(Arguments):
    title: str = Field(default="MalDroid Static Research Report", min_length=1, max_length=300)
    include_tentative: bool = True


URL_PATTERN = re.compile(rb"(?:https?|wss?)://[^\x00-\x20\"'<>]{3,2048}", re.IGNORECASE)
EMAIL_PATTERN = re.compile(rb"[A-Z0-9._%+-]{1,128}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}", re.IGNORECASE)
IP_PATTERN = re.compile(rb"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
DOMAIN_PATTERN = re.compile(
    rb"(?<![A-Z0-9_-])(?:[A-Z0-9-]{1,63}\.)+(?:com|net|org|io|co|me|app|dev|cloud|info|biz|ru|cn|xyz|top|site)(?![A-Z0-9_-])",
    re.IGNORECASE,
)

BEHAVIOR_PATTERNS: dict[str, tuple[str, ...]] = {
    "network": (
        r"https?://",
        r"wss?://",
        r"\b(?:fetch|axios|XMLHttpRequest|OkHttp|Retrofit|curl_easy_|SSL_|connect|send|recv)\b",
    ),
    "persistence": (
        r"BOOT_COMPLETED|RECEIVE_BOOT_COMPLETED|startForeground|JobScheduler|WorkManager",
        r"AccessibilityService|DeviceAdminReceiver|NotificationListenerService|VpnService",
    ),
    "identifiers": (
        r"ANDROID_ID|AdvertisingId|advertisingId|deviceId|installationId|serialNumber",
        r"getImei|getMeid|getSubscriberId|getSimSerialNumber|Settings\.Secure",
    ),
    "crypto": (
        r"AES|ChaCha|RSA|HmacSHA|MessageDigest|Cipher\.getInstance|SecretKeySpec",
        r"PBKDF2|scrypt|Argon2|encrypt|decrypt|base64",
    ),
    "dynamic_code": (
        r"\beval\s*\(|new Function|DexClassLoader|PathClassLoader|InMemoryDexClassLoader",
        r"dlopen|dlsym|System\.loadLibrary|Runtime\.getRuntime\(\)\.exec|ProcessBuilder",
    ),
    "native_bridge": (
        r"NativeModules|TurboModule|requireNativeComponent|DeviceEventEmitter|RCTDeviceEventEmitter",
        r"RegisterNatives|JNI_OnLoad|Java_[A-Za-z0-9_]+",
    ),
    "commands": (
        r"command|cmd|action|opcode|dispatch|handler|execute|payload",
        r"shell|download|upload|heartbeat|polling|websocket|pushToken",
    ),
    "webview": (
        r"WebView|addJavascriptInterface|evaluateJavascript|postMessage|onMessage",
        r"setJavaScriptEnabled|setAllowFileAccess|shouldOverrideUrlLoading|loadUrl",
    ),
}


def inventory_case(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = InventoryInput.model_validate(arguments)
    root = context.read_path(values.path)
    extensions: Counter[str] = Counter()
    largest: list[tuple[int, str]] = []
    total_size = 0
    file_count = 0
    directory_count = 0
    truncated = False
    for path in _walk_files(root):
        if path.is_dir():
            directory_count += 1
            continue
        file_count += 1
        if file_count > values.max_files:
            truncated = True
            break
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_size += size
        suffix = path.suffix.lower() or "[no extension]"
        extensions[suffix] += 1
        largest.append((size, _display_path(root, values.path, path)))
    largest.sort(reverse=True)
    selected = largest[: values.largest_count]
    return {
        "path": values.path,
        "file_count": min(file_count, values.max_files),
        "directory_count": directory_count,
        "total_size": total_size,
        "truncated": truncated,
        "extension_counts": dict(extensions.most_common(50)),
        "largest_files": [{"path": path, "size": size} for size, path in selected],
        "large_text_candidates": [
            {"path": path, "size": size}
            for size, path in selected
            if Path(path).suffix.lower()
            in {".js", ".json", ".txt", ".smali", ".java", ".kt", ".c", ".cpp"}
            and size >= 1024 * 1024
        ],
    }


def extract_network_indicators(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = NetworkIndicatorInput.model_validate(arguments)
    root = context.read_path(values.path)
    found: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    scanned = 0
    truncated_files = False
    for path in _walk_files(root):
        if not path.is_file() or _appears_binary_container(path):
            continue
        scanned += 1
        if scanned > values.max_files:
            truncated_files = True
            break
        _scan_indicators(path, _display_path(root, values.path, path), found)
    records: list[dict[str, Any]] = []
    for kind in sorted(found):
        for value, paths in sorted(found[kind].items()):
            records.append({"type": kind, "value": value, "paths": sorted(paths)[:20]})
    output_file = None
    if len(records) > values.max_results:
        target = context.output_directory() / _output_name("network-indicators", "json")
        atomic_write_json(target, records)
        output_file = target.relative_to(context.case.root).as_posix()
    counts = Counter(record["type"] for record in records)
    return {
        "path": values.path,
        "files_scanned": min(scanned, values.max_files),
        "file_scan_truncated": truncated_files,
        "counts": dict(counts),
        "total_indicators": len(records),
        "returned_indicators": min(len(records), values.max_results),
        "truncated": len(records) > values.max_results,
        "output_file": output_file,
        "indicators": records[: values.max_results],
    }


def search_behavior_patterns(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = BehaviorSearchInput.model_validate(arguments)
    target = context.read_path(values.path)
    executable = shutil.which("rg")
    categories = values.categories or [cast(BehaviorCategory, value) for value in BEHAVIOR_PATTERNS]
    output = context.output_directory() / _output_name("behavior-search", "jsonl")
    if not executable:
        return _python_behavior_search(context, target, values, categories, output)
    combined = [pattern for category in categories for pattern in BEHAVIOR_PATTERNS[category]]
    command = [
        executable,
        "--json",
        "--line-number",
        "--color",
        "never",
        "--glob",
        "!.maldroid/**",
        "--glob",
        "!tool-output/**",
    ]
    for pattern in combined:
        command.extend(["-e", pattern])
    command.extend(["--", str(target)])
    with output.open("wb") as handle:
        completed = subprocess.run(
            command,
            cwd=context.case.root,
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=context.config.limits.command_timeout_seconds,
            check=False,
        )
    if completed.returncode not in {0, 1}:
        raise ValueError(completed.stderr.decode("utf-8", errors="replace")[:2000])
    compiled = {
        category: re.compile("|".join(f"(?:{item})" for item in BEHAVIOR_PATTERNS[category]), re.I)
        for category in categories
    }
    grouped: dict[BehaviorCategory, list[dict[str, Any]]] = {
        category: [] for category in categories
    }
    totals: Counter[str] = Counter()
    with output.open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event["data"]
            line = str(data.get("lines", {}).get("text", "")).rstrip("\r\n")
            record = {
                "path": str(data.get("path", {}).get("text", "")),
                "line": data.get("line_number"),
                "preview": line[:1000],
            }
            for category, compiled_pattern in compiled.items():
                if compiled_pattern.search(line):
                    totals[category] += 1
                    if len(grouped[category]) < values.max_results_per_category:
                        grouped[category].append(record)
    return {
        "path": values.path,
        "categories": categories,
        "totals": dict(totals),
        "results": grouped,
        "truncated_categories": [
            category
            for category in categories
            if totals[category] > values.max_results_per_category
        ],
        "output_file": output.relative_to(context.case.root).as_posix(),
        "backend": "ripgrep",
        "accuracy": "Pattern matches are triage leads, not evidence of reachable behavior.",
    }


def read_byte_range(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ByteRangeInput.model_validate(arguments)
    path = context.read_path(values.path)
    if not path.is_file():
        raise ValueError("A file is required.")
    size = path.stat().st_size
    if values.start_offset >= size:
        raise ValueError(f"start_offset is beyond the end of the {size}-byte file")
    with path.open("rb") as handle:
        handle.seek(values.start_offset)
        data = handle.read(values.length)
    rows = []
    for local in range(0, len(data), 16):
        chunk = data[local : local + 16]
        rows.append(
            {
                "offset": values.start_offset + local,
                "hex": " ".join(f"{byte:02x}" for byte in chunk),
                "ascii": "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk),
            }
        )
    return {
        "path": values.path,
        "file_size": size,
        "start_offset": values.start_offset,
        "returned_bytes": len(data),
        "end_offset": values.start_offset + len(data),
        "truncated": values.start_offset + len(data) < size,
        "rows": rows,
    }


def build_research_report(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReportInput.model_validate(arguments)
    state = context.case.state
    findings = [
        item for item in state.findings if values.include_tentative or item.status != "tentative"
    ]
    open_todos = [item for item in state.todos if item.status == "open"]
    lines = [
        f"# {values.title}",
        "",
        f"- Case: {context.case.metadata.name}",
        f"- Case ID: {context.case.metadata.case_id}",
        f"- Profile: {state.active_profile}",
        f"- Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Findings: {len(findings)}",
        f"- Open research tasks: {len(open_todos)}",
        "",
        "## Scope and current assessment",
        "",
        state.summary or "No separate case summary has been recorded.",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.extend(["No findings currently match the report filter.", ""])
    for finding in findings:
        lines.extend(
            [
                f"### {finding.id}: {finding.title}",
                "",
                f"- Status: {finding.status}",
                f"- Confidence: {finding.confidence}",
                f"- Severity: {finding.severity}",
                f"- Tags: {', '.join(finding.tags) if finding.tags else 'none'}",
                "",
                finding.summary,
                "",
            ]
        )
        if finding.evidence:
            lines.extend(["Evidence:", ""])
            for reference in finding.evidence:
                location = reference.path
                if reference.start_line is not None:
                    location += f":{reference.start_line}"
                    if reference.end_line not in {None, reference.start_line}:
                        location += f"-{reference.end_line}"
                elif reference.start_offset is not None:
                    location += f"@{reference.start_offset}"
                    if reference.end_offset is not None:
                        location += f"-{reference.end_offset}"
                tool = f"; tool: {reference.tool}" if reference.tool else ""
                lines.append(f"- `{location}` — {reference.description}{tool}")
            lines.append("")
    lines.extend(["## Open research tasks", ""])
    lines.extend(f"- {item.id}: {item.text}" for item in open_todos)
    if not open_todos:
        lines.append("No open TODO items.")
    lines.extend(["", "## Latest research continuity", ""])
    if state.checkpoints:
        checkpoint = state.checkpoints[-1]
        lines.extend(
            [
                f"- Checkpoint: {checkpoint.id} ({checkpoint.status})",
                f"- Objective: {checkpoint.objective}",
                f"- Next action: {checkpoint.next_action or 'none; marked complete'}",
            ]
        )
        if checkpoint.unresolved_questions:
            lines.extend(f"- Open question: {item}" for item in checkpoint.unresolved_questions)
        if checkpoint.uncertainty:
            lines.extend(f"- Uncertainty: {item}" for item in checkpoint.uncertainty)
    else:
        lines.append("No typed research checkpoint has been recorded.")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "This report contains static-analysis conclusions only. Tentative findings and "
            "decompiler-derived claims retain their displayed confidence and require independent "
            "verification where noted.",
            "",
        ]
    )
    reports = context.case.root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / "RESEARCH_REPORT.md"
    atomic_write_text(target, "\n".join(lines))
    return {
        "path": target.relative_to(context.case.root).as_posix(),
        "finding_count": len(findings),
        "open_todo_count": len(open_todos),
        "checkpoint": state.checkpoints[-1].id if state.checkpoints else None,
    }


def register_triage_tools(registry: ToolRegistry) -> None:
    definitions: list[tuple[str, str, type[BaseModel], ToolHandler]] = [
        (
            "inventory_case",
            "Summarize file types, sizes, largest artifacts, and large-text index candidates.",
            InventoryInput,
            inventory_case,
        ),
        (
            "extract_network_indicators",
            "Extract bounded URLs, WebSockets, domains, IPs, and emails in one static pass.",
            NetworkIndicatorInput,
            extract_network_indicators,
        ),
        (
            "search_behavior_patterns",
            "Search multiple high-signal behavior families in one bounded ripgrep pass.",
            BehaviorSearchInput,
            search_behavior_patterns,
        ),
        (
            "read_byte_range",
            "Read a bounded file byte range with hexadecimal and ASCII views.",
            ByteRangeInput,
            read_byte_range,
        ),
        (
            "build_research_report",
            "Build a deterministic Markdown report from durable findings and checkpoints.",
            ReportInput,
            build_research_report,
        ),
    ]
    for name, description, model, handler in definitions:
        registry.register(ToolDefinition(name, "core", description, model, handler))


def _walk_files(root: Path) -> Any:
    if root.is_file():
        yield root
        return
    ignored = {".git", ".venv", "__pycache__", "tool-output"}
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if name not in ignored and name != ".maldroid"
        ]
        current_path = Path(current)
        yield from (current_path / name for name in sorted(files))


def _display_path(root: Path, requested: str, path: Path) -> str:
    if root.is_file():
        return requested
    relative = path.relative_to(root).as_posix()
    return relative if requested in {"", "."} else f"{requested.rstrip('/')}/{relative}"


def _appears_binary_container(path: Path) -> bool:
    if path.suffix.lower() in {
        ".so",
        ".dex",
        ".apk",
        ".aab",
        ".apks",
        ".zip",
        ".png",
        ".jpg",
        ".gif",
        ".pdf",
    }:
        return True
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return True


def _scan_indicators(path: Path, display_path: str, found: dict[str, dict[str, set[str]]]) -> None:
    carry = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            data = carry + block
            for match in URL_PATTERN.finditer(data):
                value = match.group(0).decode("utf-8", errors="replace").rstrip(".,);]}")
                kind = "websocket" if value.lower().startswith(("ws://", "wss://")) else "url"
                found[kind][value].add(display_path)
            for match in EMAIL_PATTERN.finditer(data):
                found["email"][match.group(0).decode("ascii", errors="ignore")].add(display_path)
            for match in IP_PATTERN.finditer(data):
                value = match.group(0).decode("ascii")
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    continue
                found["ip"][value].add(display_path)
            for match in DOMAIN_PATTERN.finditer(data):
                found["domain"][match.group(0).decode("ascii", errors="ignore").lower()].add(
                    display_path
                )
            carry = data[-2048:]


def _output_name(prefix: str, suffix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.{suffix}"


def _python_behavior_search(
    context: ToolContext,
    target: Path,
    values: BehaviorSearchInput,
    categories: list[BehaviorCategory],
    output: Path,
) -> dict[str, Any]:
    compiled = {
        category: [re.compile(pattern.encode(), re.I) for pattern in BEHAVIOR_PATTERNS[category]]
        for category in categories
    }
    grouped: dict[BehaviorCategory, list[dict[str, Any]]] = {
        category: [] for category in categories
    }
    totals: Counter[str] = Counter()
    scanned_files = 0
    scan_truncated = False
    deadline = time.monotonic() + context.config.limits.command_timeout_seconds
    with output.open("w", encoding="utf-8") as output_handle:
        for path in _walk_files(target):
            if not path.is_file() or _appears_binary_container(path):
                continue
            scanned_files += 1
            if scanned_files > 20000:
                scan_truncated = True
                break
            display_path = _display_path(target, values.path, path)
            carry = b""
            consumed = 0
            line_number = 1
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Behavior pattern search exceeded the configured command timeout."
                        )
                    data = carry + block
                    base = consumed - len(carry)
                    safe_length = max(0, len(data) - 4096)
                    searchable = data[:safe_length]
                    line_number = _collect_behavior_matches(
                        searchable,
                        base,
                        line_number,
                        display_path,
                        compiled,
                        grouped,
                        totals,
                        values.max_results_per_category,
                        output_handle,
                    )
                    consumed += len(block)
                    carry = data[safe_length:]
            _collect_behavior_matches(
                carry,
                consumed - len(carry),
                line_number,
                display_path,
                compiled,
                grouped,
                totals,
                values.max_results_per_category,
                output_handle,
            )
    return {
        "path": values.path,
        "categories": categories,
        "totals": dict(totals),
        "results": grouped,
        "truncated_categories": [
            category
            for category in categories
            if totals[category] > values.max_results_per_category
        ],
        "files_scanned": min(scanned_files, 20000),
        "file_scan_truncated": scan_truncated,
        "output_file": output.relative_to(context.case.root).as_posix(),
        "backend": "python-streaming",
        "accuracy": "Pattern matches are triage leads, not evidence of reachable behavior.",
    }


def _collect_behavior_matches(
    data: bytes,
    base_offset: int,
    start_line: int,
    display_path: str,
    compiled: dict[BehaviorCategory, list[re.Pattern[bytes]]],
    grouped: dict[BehaviorCategory, list[dict[str, Any]]],
    totals: Counter[str],
    result_limit: int,
    output_handle: Any,
) -> int:
    for category, patterns in compiled.items():
        for pattern in patterns:
            for match in pattern.finditer(data):
                totals[category] += 1
                preview_start = max(0, match.start() - 300)
                preview_end = min(len(data), match.end() + 300)
                record = {
                    "path": display_path,
                    "line": start_line + data[: match.start()].count(b"\n"),
                    "offset": base_offset + match.start(),
                    "preview": data[preview_start:preview_end].decode("utf-8", errors="replace")[
                        :1000
                    ],
                }
                output_handle.write(
                    json.dumps({"category": category, **record}, ensure_ascii=False) + "\n"
                )
                if len(grouped[category]) < result_limit:
                    grouped[category].append(record)
    return start_line + data.count(b"\n")
