from __future__ import annotations

import pytest

from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.large_files import LargeTextIndexer
from maldroid.paths import PathPolicy
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def test_large_text_contentless_index_search_read_and_invalidate(
    app_config: AppConfig,
) -> None:
    case = CaseManager(app_config).create()
    source = case.root / "large.txt"
    source.write_text(
        "".join(
            f"line {number} {'AccessibilityService' if number == 777 else 'normal'}\n"
            for number in range(1, 2001)
        ),
        encoding="utf-8",
    )
    indexer = LargeTextIndexer(case.root)
    created = indexer.index(source, "large.txt", 100)
    assert created["chunks"] == 20
    result = indexer.search("large.txt", "AccessibilityService", 1, 10)
    assert result["total_matches"] == 1
    chunk = indexer.read_chunk("large.txt", result["results"][0]["chunk_number"], 20000)
    assert "AccessibilityService" in chunk["content"]
    source.write_text(source.read_text() + "changed\n", encoding="utf-8")
    with pytest.raises(Exception, match="changed"):
        indexer.read_chunk("large.txt", 1, 20000)
    rebuilt = indexer.index(source, "large.txt", 100)
    assert rebuilt["status"] == "created"
    assert indexer.search("large.txt", "changed", 1, 10)["total_matches"] == 1


def test_react_native_module_index_and_bounded_search(app_config: AppConfig) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    case.state.active_profile = "react-native"
    manager.save(case)
    bundle = case.root / "index.android.bundle"
    bundle.write_text(
        "__d(function(g,r,i,a,m,e,d){const first='normal';},12,[1]);\n"
        "__d(function(g,r,i,a,m,e,d){const service='AccessibilityService';},34,[2]);\n",
        encoding="utf-8",
    )
    registry = build_registry()
    context = ToolContext(
        config=app_config,
        case=case,
        case_manager=manager,
        investigation=InvestigationManager(manager),
        path_policy=PathPolicy(case.root),
    )
    dispatcher = ToolDispatcher(registry, context)
    indexed = dispatcher.execute(mcp_tool_name("index_metro_bundle"), {"path": bundle.name})
    assert indexed.status == "completed"
    assert indexed.data["module_count"] == 2
    modules = dispatcher.execute(mcp_tool_name("list_bundle_modules"), {"path": bundle.name})
    assert [item["module"] for item in modules.data["modules"]] == ["12", "34"]
    search = dispatcher.execute(
        mcp_tool_name("search_bundle_modules"),
        {"path": bundle.name, "query": "AccessibilityService"},
    )
    assert search.data["results"][0]["module"] == "34"

    bundle.write_text(
        bundle.read_text(encoding="utf-8")
        + "__d(function(){NativeModules.CommandBridge.execute(ANDROID_ID);"
        + "fetch('https://api.example.com');},56,[]);\n",
        encoding="utf-8",
    )
    dispatcher.execute(mcp_tool_name("index_metro_bundle"), {"path": bundle.name})
    triage = dispatcher.execute(mcp_tool_name("triage_react_native_bundle"), {"path": bundle.name})
    assert triage.status == "completed"
    assert triage.data["totals"]["network"] >= 1
    assert triage.data["totals"]["identifiers"] >= 1
    assert triage.data["results"]["native_bridge"][0]["module"] == "56"
    bridges = dispatcher.execute(mcp_tool_name("list_react_native_bridges"), {"path": bundle.name})
    assert bridges.data["bridges"][0]["name"] == "CommandBridge"


def test_react_native_small_bundle_sample_does_not_count_the_head_twice(
    app_config: AppConfig,
) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    case.state.active_profile = "react-native"
    manager.save(case)
    bundle = case.root / "small.bundle"
    bundle.write_bytes(b"__d(function(){},1,[]);\n")
    dispatcher = ToolDispatcher(
        build_registry(),
        ToolContext(
            config=app_config,
            case=case,
            case_manager=manager,
            investigation=InvestigationManager(manager),
            path_policy=PathPolicy(case.root),
        ),
    )

    result = dispatcher.execute(mcp_tool_name("inspect_javascript_bundle"), {"path": bundle.name})

    assert result.status == "completed"
    assert result.data["metro_wrapper_indicators"] == 1


def test_react_native_inspection_streams_a_multi_megabyte_single_line(
    app_config: AppConfig,
) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    case.state.active_profile = "react-native"
    manager.save(case)
    bundle = case.root / "single-line.bundle"
    size = 3 * 1024 * 1024 + 17
    bundle.write_bytes(b"x" * size)
    dispatcher = ToolDispatcher(
        build_registry(),
        ToolContext(
            config=app_config,
            case=case,
            case_manager=manager,
            investigation=InvestigationManager(manager),
            path_policy=PathPolicy(case.root),
        ),
    )

    result = dispatcher.execute(mcp_tool_name("inspect_javascript_bundle"), {"path": bundle.name})

    assert result.status == "completed"
    assert result.data["line_count"] == 1
    assert result.data["longest_line_bytes"] == size
    assert result.data["appears_minified"] is True


def test_bundle_search_does_not_duplicate_matches_from_block_overlap(
    app_config: AppConfig,
) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    case.state.active_profile = "react-native"
    manager.save(case)
    marker = b"__d(function(){},1,[]);"
    needle = b"BOUNDARY_NEEDLE"
    first_block = marker + b"x" * (1024 * 1024 - len(marker) - 80) + needle
    bundle = case.root / "boundary.bundle"
    bundle.write_bytes(first_block + b"y" * 512)
    dispatcher = ToolDispatcher(
        build_registry(),
        ToolContext(
            config=app_config,
            case=case,
            case_manager=manager,
            investigation=InvestigationManager(manager),
            path_policy=PathPolicy(case.root),
        ),
    )
    dispatcher.execute(mcp_tool_name("index_metro_bundle"), {"path": bundle.name})

    result = dispatcher.execute(
        mcp_tool_name("search_bundle_modules"),
        {"path": bundle.name, "query": needle.decode()},
    )

    assert result.status == "completed"
    assert result.data["returned_matches"] == 1
