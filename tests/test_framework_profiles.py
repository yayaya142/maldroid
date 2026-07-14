from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.paths import PathPolicy
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import build_registry


def dispatcher_for(app_config: AppConfig, profile: str):
    manager = CaseManager(app_config)
    case = manager.create()
    case.state.active_profile = profile
    manager.save(case)
    registry = build_registry()
    context = ToolContext(
        config=app_config,
        case=case,
        case_manager=manager,
        investigation=InvestigationManager(manager),
        path_policy=PathPolicy(case.root),
    )
    return case, registry, ToolDispatcher(registry, context)


def test_each_profile_exposes_only_core_and_its_tools(app_config: AppConfig) -> None:
    _, registry, _ = dispatcher_for(app_config, "generic")
    generic = set(registry.names("generic"))
    expectations = {
        "native": "inspect_elf_file",
        "flutter": "inspect_flutter_artifacts",
        "unity": "detect_unity_backend",
        "cordova": "inspect_cordova_config",
        "cocos": "detect_cocos_script_type",
    }
    for profile, expected in expectations.items():
        names = set(registry.names(profile))
        assert generic < names
        assert expected in names
        for other_profile, other_tool in expectations.items():
            if other_profile != profile:
                assert other_tool not in names


def test_flutter_inventory_and_unconfigured_blutter(app_config: AppConfig) -> None:
    case, _, dispatcher = dispatcher_for(app_config, "flutter")
    (case.root / "libapp.so").write_bytes(b"not-executed")
    inspected = dispatcher.execute("inspect_flutter_artifacts", {"path": "."})
    assert inspected.data["flutter_aot_indicators"] is True
    availability = dispatcher.execute("check_blutter_availability", {})
    assert availability.data["available"] is False


def test_unity_cordova_and_cocos_static_detection(app_config: AppConfig) -> None:
    unity_case, _, unity = dispatcher_for(app_config, "unity")
    (unity_case.root / "global-metadata.dat").write_bytes(b"metadata")
    (unity_case.root / "libil2cpp.so").write_bytes(b"ELF-placeholder")
    backend = unity.execute("detect_unity_backend", {"path": "."})
    assert "IL2CPP" in backend.data["detected_backends"]

    cordova_case, _, cordova = dispatcher_for(app_config, "cordova")
    (cordova_case.root / "config.xml").write_text(
        '<widget id="example"><content src="index.html"/><plugin name="cordova-plugin-device" spec="2.1.0"/></widget>',
        encoding="utf-8",
    )
    config = cordova.execute("inspect_cordova_config", {"path": "config.xml"})
    assert config.data["root_attributes"]["id"] == "example"
    plugins = cordova.execute("list_cordova_plugins", {"path": "."})
    assert plugins.data["plugins"][0]["id"] == "cordova-plugin-device"

    cocos_case, _, cocos = dispatcher_for(app_config, "cocos")
    (cocos_case.root / "main.lua").write_text("print('static')", encoding="utf-8")
    (cocos_case.root / "compiled.luac").write_bytes(b"compiled")
    detected = cocos.execute("detect_cocos_script_type", {"path": "."})
    types = {item["type"] for item in detected.data["script_types"]}
    assert {"lua-text", "compiled-lua"} <= types


@pytest.mark.skipif(not shutil.which("readelf"), reason="readelf is not installed")
def test_native_profile_inspects_benign_host_elf(app_config: AppConfig) -> None:
    source = Path(shutil.which("true") or "/bin/true")
    case, _, dispatcher = dispatcher_for(app_config, "native")
    target = case.root / "benign-elf"
    shutil.copy2(source, target)
    result = dispatcher.execute("inspect_elf_file", {"path": target.name})
    assert result.status == "completed"
    assert "ELF Header" in result.data["preview"]
