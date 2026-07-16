from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from maldroid.case_manager import Case, CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.paths import PathPolicy
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def make_dispatcher(config: AppConfig) -> tuple[Case, ToolDispatcher]:
    manager = CaseManager(config)
    case = manager.create("Triage")
    context = ToolContext(
        config=config,
        case=case,
        case_manager=manager,
        investigation=InvestigationManager(manager),
        path_policy=PathPolicy(case.root),
    )
    return case, ToolDispatcher(build_registry(), context)


def test_inventory_highlights_large_text_candidates(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "bundle.js").write_text("x" * (1024 * 1024 + 10), encoding="utf-8")
    (case.root / "classes.dex").write_bytes(b"dex\n035\x00")
    (case.root / "sources" / "nested").mkdir(parents=True)

    result = dispatcher.execute(mcp_tool_name("inventory_case"), {"path": "."})

    assert result.status == "completed"
    assert result.data["extension_counts"][".js"] == 1
    assert result.data["large_text_candidates"][0]["path"] == "bundle.js"
    assert result.data["directory_count"] >= 2


def test_network_indicator_extraction_deduplicates_and_records_paths(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "bundle.js").write_text(
        'const api="https://api.example.com/v1"; const ws="wss://push.example.com/socket";\n'
        'const mail="ops@example.org"; const ip="192.0.2.10";\n',
        encoding="utf-8",
    )

    result = dispatcher.execute(mcp_tool_name("extract_network_indicators"), {"path": "bundle.js"})

    assert result.status == "completed"
    values = {item["value"] for item in result.data["indicators"]}
    assert "https://api.example.com/v1" in values
    assert "wss://push.example.com/socket" in values
    assert "192.0.2.10" in values
    assert result.data["counts"]["url"] == 1
    assert result.data["counts"]["websocket"] == 1


def test_network_indicator_scan_skips_nested_symlink_files(
    app_config: AppConfig, tmp_path: Path
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    outside = tmp_path / "outside.js"
    outside.write_text('const leaked = "https://outside.invalid/secret";', encoding="utf-8")
    (case.root / "outside-link.js").symlink_to(outside)

    result = dispatcher.execute(mcp_tool_name("extract_network_indicators"), {"path": "."})

    assert result.status == "completed"
    assert result.data["total_indicators"] == 0


def test_network_indicator_scan_stops_at_the_unique_result_budget(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "many-urls.js").write_text(
        "\n".join(f"https://host{number}.example/path" for number in range(100)),
        encoding="utf-8",
    )

    result = dispatcher.execute(
        mcp_tool_name("extract_network_indicators"),
        {"path": ".", "max_results": 2},
    )

    assert result.status == "completed"
    assert result.data["returned_indicators"] == 2
    assert result.data["total_indicators"] == 3
    assert result.data["total_indicators_exact"] is False
    assert result.data["truncation_reason"] == "result_budget"


def test_behavior_search_groups_multiple_research_leads(app_config: AppConfig, monkeypatch) -> None:
    monkeypatch.setattr("maldroid.tools.core.triage.shutil.which", lambda _: None)
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.js").write_text(
        "const id = ANDROID_ID;\nfetch('https://example.com', {body: id});\n"
        "NativeModules.CommandBridge.execute(payload);\n",
        encoding="utf-8",
    )

    result = dispatcher.execute(
        mcp_tool_name("search_behavior_patterns"),
        {
            "path": "sample.js",
            "categories": ["network", "identifiers", "native_bridge", "commands"],
        },
    )

    assert result.status == "completed"
    assert result.data["totals"]["network"] >= 1
    assert result.data["totals"]["identifiers"] >= 1
    assert result.data["totals"]["native_bridge"] >= 1
    assert result.data["output_file"].startswith("tool-output/behavior-search-")
    assert result.data["backend"] == "python-streaming"


def test_behavior_search_bounds_the_durable_match_artifact(
    app_config: AppConfig, monkeypatch
) -> None:
    monkeypatch.setattr("maldroid.tools.core.triage.shutil.which", lambda _: None)
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "repeated.js").write_text(
        "".join(f"fetch(request{number});\n" for number in range(100)),
        encoding="utf-8",
    )

    result = dispatcher.execute(
        mcp_tool_name("search_behavior_patterns"),
        {
            "path": "repeated.js",
            "categories": ["network"],
            "max_results_per_category": 2,
        },
    )

    output = case.root / result.data["output_file"]
    assert result.status == "completed"
    assert result.data["totals_exact"] is False
    assert result.data["truncation_reason"] == "result_budget"
    assert len(result.data["results"]["network"]) == 2
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep is not installed")
def test_ripgrep_behavior_search_stops_at_the_cross_category_budget(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "repeated-rg.js").write_text(
        "".join(f"fetch(request{number});\n" for number in range(100)),
        encoding="utf-8",
    )

    result = dispatcher.execute(
        mcp_tool_name("search_behavior_patterns"),
        {
            "path": "repeated-rg.js",
            "categories": ["network"],
            "max_results_per_category": 2,
        },
    )

    output = case.root / result.data["output_file"]
    assert result.status == "completed"
    assert result.data["backend"] == "ripgrep"
    assert result.data["totals_exact"] is False
    assert result.data["totals"]["network"] == 3
    assert result.data["results"]["network"][0]["path"] == "repeated-rg.js"
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_byte_range_returns_exact_offsets_hex_and_ascii(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.bin").write_bytes(b"\x00ABCDEF\xff")

    result = dispatcher.execute(
        mcp_tool_name("read_byte_range"),
        {"path": "sample.bin", "start_offset": 1, "length": 4},
    )

    assert result.status == "completed"
    assert result.data["returned_bytes"] == 4
    assert result.data["rows"][0] == {"offset": 1, "hex": "41 42 43 44", "ascii": "ABCD"}


def test_report_is_built_from_durable_research_state(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    dispatcher.execute(
        mcp_tool_name("save_finding"),
        {
            "title": "Static endpoint",
            "summary": "A request builder references a fixed endpoint.",
            "evidence": [{"path": "bundle.js", "start_offset": 120}],
            "tags": ["network"],
        },
    )
    dispatcher.execute(
        mcp_tool_name("save_checkpoint"),
        {
            "objective": "Trace network behavior",
            "completed_work": ["Mapped the request builder"],
            "next_action": "Verify callers",
        },
    )

    result = dispatcher.execute(mcp_tool_name("build_research_report"), {})

    assert result.status == "completed"
    report = (case.root / result.data["path"]).read_text(encoding="utf-8")
    assert "FIND-0001: Static endpoint" in report
    assert "CHECK-0001" in report
    assert "Verify callers" in report
