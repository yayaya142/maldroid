"""Bounded static tools for Flutter, Unity, Cordova, and Cocos artifacts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TypeAlias

from defusedxml import ElementTree as ET
from pydantic import BaseModel, ConfigDict, Field

from maldroid.paths import expand_path
from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.profiles.common import bounded_read, exact_search, inventory, run_allowlisted
from maldroid.tools.registry import ToolRegistry

ToolList: TypeAlias = list[tuple[str, str, type[BaseModel], ToolHandler]]


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactInput(Arguments):
    path: str = "."


class SearchInput(ArtifactInput):
    query: str = Field(min_length=1, max_length=1000)


class ReadInput(Arguments):
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class StringsInput(Arguments):
    path: str
    minimum_length: int = Field(default=6, ge=3, le=256)


class RunBlutterInput(Arguments):
    libapp_path: str
    output_name: str = Field(default="blutter-output", pattern=r"^[A-Za-z0-9._-]+$")


def inspect_flutter_artifacts(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    artifacts = inventory(
        context,
        values.path,
        names={"libapp.so", "libflutter.so", "isolate_snapshot_data", "vm_snapshot_data"},
        suffixes={".so", ".dill", ".symbols"},
    )
    return {
        "artifacts": artifacts,
        "flutter_aot_indicators": any(item["name"].lower() == "libapp.so" for item in artifacts),
        "note": "Version compatibility must be established before running Blutter.",
    }


def check_blutter_availability(context: ToolContext, _: BaseModel) -> dict[str, Any]:
    configured = context.config.external_tools.blutter or os.environ.get("MALDROID_BLUTTER")
    if not configured:
        return {"available": False, "reason": "external_tools.blutter is not configured"}
    target = expand_path(configured)
    script = target / "blutter.py" if target.is_dir() else target
    available = script.is_file()
    return {
        "available": available,
        "configured_path": str(target),
        "script": str(script),
        "reason": None if available else "The configured Blutter script does not exist.",
    }


def run_blutter(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = RunBlutterInput.model_validate(arguments)
    availability = check_blutter_availability(context, Arguments())
    if not availability["available"]:
        raise ValueError(str(availability["reason"]))
    libapp = context.read_path(values.libapp_path)
    if not libapp.is_file() or libapp.name != "libapp.so":
        raise ValueError("run_blutter requires a registered libapp.so artifact.")
    script = Path(str(availability["script"]))
    output = context.output_directory() / values.output_name
    if output.exists():
        raise ValueError(f"Blutter output already exists: {output.name}")
    output.mkdir()
    stdout_path = output / "blutter.stdout.log"
    stderr_path = output / "blutter.stderr.log"
    command = [sys.executable, str(script), str(libapp), str(output)]
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            cwd=script.parent,
            timeout=context.config.limits.command_timeout_seconds,
            check=False,
        )
    if completed.returncode:
        raise ValueError(
            f"Blutter exited with {completed.returncode}: "
            + stderr_path.read_text(errors="replace")[:4000]
        )
    return {
        "command": ["python", str(script), values.libapp_path, output.name],
        "exit_status": completed.returncode,
        "output_directory": output.relative_to(context.case.root).as_posix(),
        "compatibility": "The caller must verify the Flutter/Dart version against Blutter support.",
    }


def search_flutter_output(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchInput.model_validate(arguments)
    return exact_search(context, values.path, values.query, {".dart", ".txt", ".json", ".asm"})


def read_flutter_output(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReadInput.model_validate(arguments)
    return bounded_read(context, values.path, values.start_line, values.end_line)


def extract_flutter_strings(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = StringsInput.model_validate(arguments)
    path = context.read_path(values.path)
    return run_allowlisted(
        context,
        "strings",
        ["-n", str(values.minimum_length), str(path)],
        "flutter-strings",
    )


def inspect_unity_artifacts(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    artifacts = inventory(
        context,
        values.path,
        names={"global-metadata.dat", "libil2cpp.so"},
        suffixes={".dll", ".cs", ".so", ".dat"},
    )
    return {"artifacts": artifacts, **_unity_backend(artifacts)}


def detect_unity_backend(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    return _unity_backend(inspect_unity_artifacts(context, arguments)["artifacts"])


def _unity_backend(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    names = {item["name"].lower() for item in artifacts}
    il2cpp = {"global-metadata.dat", "libil2cpp.so"} <= names
    mono = any(name.endswith(".dll") for name in names)
    backends = [name for name, present in (("IL2CPP", il2cpp), ("Mono", mono)) if present]
    return {
        "detected_backends": backends,
        "certainty": "artifact-indicator",
        "note": "Mixed or incomplete extraction can expose indicators for more than one backend.",
    }


def search_managed_code(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchInput.model_validate(arguments)
    return exact_search(context, values.path, values.query, {".cs", ".il", ".txt"})


def search_il2cpp_output(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchInput.model_validate(arguments)
    return exact_search(
        context, values.path, values.query, {".c", ".cc", ".cpp", ".h", ".txt", ".json"}
    )


def inspect_cordova_artifacts(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    artifacts = inventory(
        context,
        values.path,
        names={"config.xml", "plugin.xml", "cordova.js"},
        suffixes={".js", ".html", ".xml"},
    )
    names = {item["name"].lower() for item in artifacts}
    return {
        "artifacts": artifacts,
        "cordova_indicators": sorted(names & {"config.xml", "cordova.js"}),
    }


def inspect_cordova_config(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    path = context.read_path(values.path)
    if path.name.lower() != "config.xml":
        raise ValueError("inspect_cordova_config requires config.xml.")
    root = ET.parse(path).getroot()
    if root is None:
        raise ValueError("Cordova configuration has no XML root element.")
    selected: list[dict[str, Any]] = []
    for element in root.iter():
        local = element.tag.rsplit("}", 1)[-1]
        if local in {"content", "access", "allow-navigation", "preference", "plugin", "feature"}:
            selected.append({"element": local, "attributes": dict(element.attrib)})
    return {
        "path": values.path,
        "root_attributes": dict(root.attrib),
        "selected_elements": selected,
    }


def list_cordova_plugins(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    root = context.read_path(values.path)
    files = [root] if root.is_file() else list(root.rglob("*.xml"))
    plugins: list[dict[str, Any]] = []
    for path in files[:500]:
        if path.name.lower() not in {"config.xml", "plugin.xml"}:
            continue
        try:
            xml_root = ET.parse(path).getroot()
            if xml_root is None:
                continue
            if xml_root.tag.rsplit("}", 1)[-1] == "plugin" and xml_root.attrib.get("id"):
                plugins.append(
                    {
                        "id": xml_root.attrib["id"],
                        "version": xml_root.attrib.get("version"),
                        "source": path.name,
                    }
                )
            for element in xml_root.iter():
                if element.tag.rsplit("}", 1)[-1] == "plugin" and element.attrib.get("name"):
                    plugins.append(
                        {
                            "id": element.attrib["name"],
                            "version": element.attrib.get("spec"),
                            "source": path.name,
                        }
                    )
        except ET.ParseError:
            continue
    return {"plugins": plugins}


def search_cordova_javascript(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchInput.model_validate(arguments)
    return exact_search(context, values.path, values.query, {".js", ".html", ".ts"})


def find_cordova_bridge_usage(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    indicators = {}
    for query in ("cordova.exec", "Cordova.exec", "addJavascriptInterface"):
        result = exact_search(context, values.path, query, {".js", ".java", ".kt", ".html"}, 50)
        if result["total_matches"]:
            indicators[query] = result
    return {"indicators": indicators, "matching": "exact textual bridge indicators"}


def inspect_cocos_artifacts(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ArtifactInput.model_validate(arguments)
    artifacts = inventory(context, values.path, suffixes={".js", ".lua", ".jsc", ".luac", ".so"})
    return {"artifacts": artifacts, "script_types": _cocos_types(artifacts)}


def detect_cocos_script_type(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    return {"script_types": _cocos_types(inspect_cocos_artifacts(context, arguments)["artifacts"])}


def _cocos_types(artifacts: list[dict[str, Any]]) -> list[dict[str, str]]:
    output = []
    for item in artifacts:
        suffix = Path(item["name"]).suffix.lower()
        kind = {
            ".js": "javascript-text",
            ".lua": "lua-text",
            ".jsc": "compiled-or-encrypted-javascript",
            ".luac": "compiled-lua",
            ".so": "native-library",
        }.get(suffix, "unknown")
        output.append({"path": item["path"], "type": kind})
    return output


def search_cocos_scripts(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = SearchInput.model_validate(arguments)
    return exact_search(context, values.path, values.query, {".js", ".lua"})


def read_cocos_script_range(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = ReadInput.model_validate(arguments)
    if Path(values.path).suffix.lower() not in {".js", ".lua", ".txt"}:
        raise ValueError("Only plaintext Cocos script output can be read as lines.")
    return bounded_read(context, values.path, values.start_line, values.end_line)


def extract_cocos_strings(context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
    values = StringsInput.model_validate(arguments)
    path = context.read_path(values.path)
    return run_allowlisted(
        context,
        "strings",
        ["-n", str(values.minimum_length), str(path)],
        "cocos-strings",
    )


def register_framework_tools(registry: ToolRegistry) -> None:
    flutter: ToolList = [
        (
            "inspect_flutter_artifacts",
            "Inventory static Flutter AOT and asset indicators.",
            ArtifactInput,
            inspect_flutter_artifacts,
        ),
        (
            "check_blutter_availability",
            "Check the configured optional Blutter script.",
            Arguments,
            check_blutter_availability,
        ),
        (
            "run_blutter",
            "Run the configured Blutter adapter explicitly and save output.",
            RunBlutterInput,
            run_blutter,
        ),
        (
            "search_blutter_output",
            "Search existing Blutter or Dart output.",
            SearchInput,
            search_flutter_output,
        ),
        (
            "read_blutter_output_range",
            "Read a bounded range from Blutter output.",
            ReadInput,
            read_flutter_output,
        ),
        (
            "find_dart_symbol",
            "Find exact symbol text in existing Dart output.",
            SearchInput,
            search_flutter_output,
        ),
        (
            "extract_flutter_strings",
            "Extract static strings from a Flutter artifact.",
            StringsInput,
            extract_flutter_strings,
        ),
    ]
    unity: ToolList = [
        (
            "inspect_unity_artifacts",
            "Inventory Unity managed and IL2CPP indicators.",
            ArtifactInput,
            inspect_unity_artifacts,
        ),
        (
            "detect_unity_backend",
            "Detect Mono and IL2CPP from supplied artifacts.",
            ArtifactInput,
            detect_unity_backend,
        ),
        (
            "search_managed_code",
            "Search existing managed-code text output.",
            SearchInput,
            search_managed_code,
        ),
        (
            "search_il2cpp_output",
            "Search existing IL2CPP text output.",
            SearchInput,
            search_il2cpp_output,
        ),
        (
            "read_managed_symbol",
            "Locate a managed symbol in existing text output.",
            SearchInput,
            search_managed_code,
        ),
        (
            "read_il2cpp_symbol",
            "Locate an IL2CPP symbol in existing text output.",
            SearchInput,
            search_il2cpp_output,
        ),
    ]
    cordova: ToolList = [
        (
            "inspect_cordova_artifacts",
            "Inventory Cordova WebView and configuration artifacts.",
            ArtifactInput,
            inspect_cordova_artifacts,
        ),
        (
            "list_cordova_plugins",
            "List plugins from config.xml and plugin.xml.",
            ArtifactInput,
            list_cordova_plugins,
        ),
        (
            "search_cordova_javascript",
            "Search Cordova JavaScript and HTML.",
            SearchInput,
            search_cordova_javascript,
        ),
        (
            "inspect_cordova_config",
            "Parse selected static Cordova config.xml elements.",
            ArtifactInput,
            inspect_cordova_config,
        ),
        (
            "find_cordova_bridge_usage",
            "Find exact JavaScript/native bridge indicators.",
            ArtifactInput,
            find_cordova_bridge_usage,
        ),
    ]
    cocos: ToolList = [
        (
            "inspect_cocos_artifacts",
            "Inventory Cocos script and native artifacts.",
            ArtifactInput,
            inspect_cocos_artifacts,
        ),
        (
            "detect_cocos_script_type",
            "Classify Cocos script files without pretending to decode them.",
            ArtifactInput,
            detect_cocos_script_type,
        ),
        (
            "search_cocos_scripts",
            "Search plaintext Cocos JavaScript and Lua.",
            SearchInput,
            search_cocos_scripts,
        ),
        (
            "read_cocos_script_range",
            "Read a bounded plaintext Cocos script range.",
            ReadInput,
            read_cocos_script_range,
        ),
        (
            "extract_cocos_strings",
            "Extract static strings from compiled Cocos artifacts.",
            StringsInput,
            extract_cocos_strings,
        ),
    ]
    for profile, definitions in (
        ("flutter", flutter),
        ("unity", unity),
        ("cordova", cordova),
        ("cocos", cocos),
    ):
        for name, description, model, handler in definitions:
            registry.register(ToolDefinition(name, profile, description, model, handler))
