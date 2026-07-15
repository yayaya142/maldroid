from __future__ import annotations

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

    result = dispatcher.execute(mcp_tool_name("inventory_case"), {"path": "."})

    assert result.status == "completed"
    assert result.data["extension_counts"][".js"] == 1
    assert result.data["large_text_candidates"][0]["path"] == "bundle.js"


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


def test_behavior_search_groups_multiple_research_leads(app_config: AppConfig) -> None:
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
