"""Allowlisted static ELF and disassembly profile tools."""

from __future__ import annotations

import re
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
    matches = [
        line for line in output.read_text(errors="replace").splitlines() if values.query in line
    ]
    result.update(
        {
            "query": values.query,
            "total_matches": len(matches),
            "matches": matches[: context.config.limits.max_search_results],
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
    matches = [
        line for line in output.read_text(errors="replace").splitlines() if values.query in line
    ]
    result.update(
        {
            "query": values.query,
            "total_matches": len(matches),
            "matches": matches[: context.config.limits.max_search_results],
        }
    )
    return result


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
