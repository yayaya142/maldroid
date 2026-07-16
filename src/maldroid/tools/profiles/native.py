"""Allowlisted static ELF and disassembly profile tools."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.profiles.common import run_allowlisted
from maldroid.tools.registry import ToolRegistry


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ElfInput(Arguments):
    path: str


class StringSearchInput(ElfInput):
    query: str = Field(min_length=1, max_length=500)
    minimum_length: int = Field(default=6, ge=3, le=256)


class DisassemblyRangeInput(ElfInput):
    start_address: str
    stop_address: str

    @field_validator("start_address", "stop_address")
    @classmethod
    def address(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0x)?[0-9A-Fa-f]{1,16}", value):
            raise ValueError("Addresses must be hexadecimal integers.")
        return hex(int(value, 16))


class DisassemblySearchInput(ElfInput):
    query: str = Field(min_length=1, max_length=500)


def inspect_elf_file(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic != b"\x7fELF":
        raise ValueError("The requested file does not have an ELF header.")
    result = run_allowlisted(context, "readelf", ["-h", str(path)], "elf-header")
    result["path"] = values.path
    result["exact_parsing"] = True
    return result


def list_elf_sections(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    return run_allowlisted(context, "readelf", ["-W", "-S", str(path)], "elf-sections")


def list_elf_symbols(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    return run_allowlisted(context, "readelf", ["-W", "-s", str(path)], "elf-symbols")


def inspect_native_dependencies(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    result = run_allowlisted(context, "readelf", ["-W", "-d", str(path)], "elf-dynamic")
    output = context.case.root / result["output_file"]
    needed: list[str] = []
    soname = None
    has_runpath = False
    has_bind_now = False
    with output.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if match := re.search(r"\(NEEDED\).*?\[([^]]+)]", line):
                needed.append(match.group(1))
            if soname is None and (match := re.search(r"\(SONAME\).*?\[([^]]+)]", line)):
                soname = match.group(1)
            has_runpath = has_runpath or "(RUNPATH)" in line or "(RPATH)" in line
            has_bind_now = (
                has_bind_now or "BIND_NOW" in line or ("FLAGS_1" in line and "NOW" in line)
            )
    result.update(
        {
            "path": values.path,
            "needed_libraries": needed,
            "soname": soname,
            "has_runpath": has_runpath,
            "has_bind_now": has_bind_now,
        }
    )
    return result


def list_elf_relocations(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    return run_allowlisted(context, "readelf", ["-W", "-r", str(path)], "elf-relocations")


def inspect_jni_surface(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    result = run_allowlisted(context, "readelf", ["-W", "-s", str(path)], "jni-symbols")
    output = context.case.root / result["output_file"]
    exports: set[str] = set()
    indicators: set[str] = set()
    with output.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if match := re.search(r"Java_[A-Za-z0-9_]+", line):
                exports.add(match.group(0))
            indicators.update(
                indicator
                for indicator in (
                    "JNI_OnLoad",
                    "RegisterNatives",
                    "GetMethodID",
                    "CallObjectMethod",
                )
                if indicator in line
            )
    sorted_exports = sorted(exports)
    sorted_indicators = sorted(indicators)
    result.update(
        {
            "path": values.path,
            "static_jni_exports": sorted_exports[:500],
            "static_jni_export_count": len(sorted_exports),
            "dynamic_jni_indicators": sorted_indicators,
            "next_step": (
                "Trace JNI_OnLoad/RegisterNatives in Ghidra to recover dynamic class and method mappings."
                if "JNI_OnLoad" in indicators or "RegisterNatives" in indicators
                else "Correlate static Java_* exports with Java/Kotlin native declarations."
            ),
        }
    )
    return result


def inspect_native_hardening(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ElfInput.model_validate(arguments)
    path = context.read_path(values.path)
    program = run_allowlisted(context, "readelf", ["-W", "-l", str(path)], "elf-program-headers")
    symbols = run_allowlisted(context, "readelf", ["-W", "-s", str(path)], "elf-hardening-symbols")
    stack_line = ""
    gnu_relro = False
    with (context.case.root / program["output_file"]).open(
        encoding="utf-8", errors="replace"
    ) as handle:
        for line in handle:
            if not stack_line and "GNU_STACK" in line:
                stack_line = line
            gnu_relro = gnu_relro or "GNU_RELRO" in line
    stack_canary = False
    fortify = False
    with (context.case.root / symbols["output_file"]).open(
        encoding="utf-8", errors="replace"
    ) as handle:
        for line in handle:
            stack_canary = stack_canary or "__stack_chk_fail" in line
            fortify = fortify or "_chk@" in line or "_chk" in line
    return {
        "path": values.path,
        "nx_stack": not any("E" in token for token in stack_line.split()[-2:])
        if stack_line
        else None,
        "gnu_relro": gnu_relro,
        "stack_canary": stack_canary,
        "fortify": fortify,
        "program_headers_output": program["output_file"],
        "symbols_output": symbols["output_file"],
        "accuracy": "Hardening indicators are static heuristics and should be verified against ELF flags.",
    }


def search_native_strings(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = StringSearchInput.model_validate(arguments)
    path = context.read_path(values.path)
    result = run_allowlisted(
        context,
        "strings",
        ["-n", str(values.minimum_length), str(path)],
        "native-strings",
    )
    output = context.case.root / result["output_file"]
    total, matches = _matching_lines(output, values.query, context.config.limits.max_search_results)
    result.update(
        {
            "query": values.query,
            "total_matches": total,
            "matches": matches,
        }
    )
    return result


def read_disassembly_range(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = DisassemblyRangeInput.model_validate(arguments)
    start = int(values.start_address, 16)
    stop = int(values.stop_address, 16)
    if stop <= start or stop - start > 1024 * 1024:
        raise ValueError("Disassembly range must be ordered and no larger than 1 MiB.")
    path = context.read_path(values.path)
    return run_allowlisted(
        context,
        "objdump",
        ["-d", f"--start-address={start}", f"--stop-address={stop}", str(path)],
        "disassembly-range",
    )


def search_disassembly(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = DisassemblySearchInput.model_validate(arguments)
    path = context.read_path(values.path)
    result = run_allowlisted(context, "objdump", ["-d", str(path)], "disassembly")
    output = context.case.root / result["output_file"]
    total, matches = _matching_lines(output, values.query, context.config.limits.max_search_results)
    result.update(
        {
            "query": values.query,
            "total_matches": total,
            "matches": matches,
        }
    )
    return result


def _matching_lines(path: Path, query: str, limit: int) -> tuple[int, list[str]]:
    total = 0
    matches: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if query not in line:
                continue
            total += 1
            if len(matches) < limit:
                matches.append(line.rstrip("\r\n")[:2000])
    return total, matches


def register_native_tools(registry: ToolRegistry) -> None:
    definitions: list[tuple[str, str, type[BaseModel], ToolHandler]] = [
        (
            "inspect_elf_file",
            "Parse the ELF header with allowlisted readelf.",
            ElfInput,
            inspect_elf_file,
        ),
        (
            "list_elf_sections",
            "List ELF sections with allowlisted readelf.",
            ElfInput,
            list_elf_sections,
        ),
        (
            "list_elf_symbols",
            "List ELF symbols with allowlisted readelf.",
            ElfInput,
            list_elf_symbols,
        ),
        (
            "inspect_native_dependencies",
            "Parse ELF dependencies, SONAME, runpath, and immediate-binding indicators.",
            ElfInput,
            inspect_native_dependencies,
        ),
        (
            "list_elf_relocations",
            "Save the bounded static ELF relocation inventory.",
            ElfInput,
            list_elf_relocations,
        ),
        (
            "inspect_jni_surface",
            "Inventory static JNI exports and dynamic registration indicators for Ghidra tracing.",
            ElfInput,
            inspect_jni_surface,
        ),
        (
            "inspect_native_hardening",
            "Summarize NX, RELRO, stack-canary, and fortify indicators with source outputs.",
            ElfInput,
            inspect_native_hardening,
        ),
        (
            "search_native_strings",
            "Extract and search static native strings.",
            StringSearchInput,
            search_native_strings,
        ),
        (
            "read_disassembly_range",
            "Disassemble one bounded address range.",
            DisassemblyRangeInput,
            read_disassembly_range,
        ),
        (
            "search_disassembly",
            "Save and search static objdump disassembly.",
            DisassemblySearchInput,
            search_disassembly,
        ),
    ]
    for name, description, model, handler in definitions:
        registry.register(ToolDefinition(name, "native", description, model, handler))
