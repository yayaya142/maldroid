from __future__ import annotations

import base64
import json
import sqlite3
import warnings
import zipfile

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.llama_client import AssistantMessage, ToolCall
from maldroid.paths import PathPolicy
from maldroid.session_manager import SessionManager
from maldroid.speed import SpeedMode
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def make_dispatcher(config: AppConfig) -> tuple[CaseManager, Case, ToolDispatcher]:
    manager = CaseManager(config)
    case = manager.create("Research tools")
    context = ToolContext(
        config=config,
        case=case,
        case_manager=manager,
        investigation=InvestigationManager(manager),
        path_policy=PathPolicy(case.root),
    )
    return manager, case, ToolDispatcher(build_registry(), context)


def test_inspect_file_combines_magic_hashes_encoding_and_entropy(app_config: AppConfig) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    sample = case.root / "classes.dex"
    sample.write_bytes(b"dex\n035\x00" + bytes(range(256)) * 4)

    result = dispatcher.execute(mcp_tool_name("inspect_file"), {"path": sample.name})
    disguised = case.root / "classes.txt"
    disguised.write_bytes(sample.read_bytes())
    conflict = dispatcher.execute(mcp_tool_name("inspect_file"), {"path": disguised.name})

    assert result.status == "completed"
    assert result.data["format"] == "Android DEX"
    assert result.data["format_confidence"] == "high"
    assert result.data["extension_conflicts_with_magic"] is False
    assert conflict.data["extension_conflicts_with_magic"] is True
    assert result.data["scan_complete"] is True
    assert len(result.data["hashes"]["sha256"]) == 64
    assert result.data["entropy_bits_per_byte"] > 7
    assert result.data["encoding"] == "binary"


def test_archive_inventory_flags_unsafe_and_duplicate_names_without_extracting(
    app_config: AppConfig,
) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    archive_path = case.root / "sample.apk"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("assets/config.json", b'{"endpoint":"https://example.test"}')
            archive.writestr("../escape.txt", b"must remain inside archive")
            archive.writestr("duplicate.txt", b"one")
            archive.writestr("duplicate.txt", b"two")

    inventory = dispatcher.execute(
        mcp_tool_name("inspect_archive"),
        {"path": archive_path.name, "name_query": "txt"},
    )
    entry = dispatcher.execute(
        mcp_tool_name("read_archive_entry"),
        {"path": archive_path.name, "entry": "assets/config.json", "max_bytes": 10},
    )
    duplicate = dispatcher.execute(
        mcp_tool_name("read_archive_entry"),
        {"path": archive_path.name, "entry": "duplicate.txt"},
    )

    assert inventory.status == "completed"
    assert inventory.data["unsafe_path_entries"] == 1
    assert inventory.data["duplicate_entry_names"] == ["duplicate.txt"]
    assert entry.data["text_preview"] == '{"endpoint'
    assert entry.data["truncated"] is True
    assert duplicate.status == "error"
    assert not (case.root.parent / "escape.txt").exists()


def test_structured_data_queries_json_and_rejects_yaml_aliases(app_config: AppConfig) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    (case.root / "config.json").write_text(
        json.dumps({"api": {"hosts": ["one", "two"]}}), encoding="utf-8"
    )
    (case.root / "aliases.yaml").write_text(
        "base: &base\n  token: value\ncopy: *base\n", encoding="utf-8"
    )

    queried = dispatcher.execute(
        mcp_tool_name("inspect_structured_data"),
        {"path": "config.json", "query": "api.hosts[1]"},
    )
    aliases = dispatcher.execute(
        mcp_tool_name("inspect_structured_data"),
        {"path": "aliases.yaml"},
    )

    assert queried.status == "completed"
    assert queried.data["value"] == "two"
    assert aliases.status == "error"
    assert "aliases are disabled" in aliases.error.message


def test_sqlite_inspection_is_immutable_and_supports_schema_sample_search(
    app_config: AppConfig,
) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    database = case.root / "events.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT, payload BLOB)")
    connection.executemany(
        "INSERT INTO events(kind, payload) VALUES (?, ?)",
        [("startup", b"one"), ("command", b"secret-marker")],
    )
    connection.commit()
    connection.close()

    schema = dispatcher.execute(mcp_tool_name("inspect_sqlite"), {"path": database.name})
    sample = dispatcher.execute(
        mcp_tool_name("inspect_sqlite"),
        {"path": database.name, "action": "sample", "table": "events", "limit": 1},
    )
    search = dispatcher.execute(
        mcp_tool_name("inspect_sqlite"),
        {"path": database.name, "action": "search", "query": "command"},
    )

    assert schema.status == "completed"
    assert schema.data["mode"] == "read-only immutable"
    assert schema.data["tables"][0]["table"] == "events"
    assert sample.data["rows"][0]["payload"]["type"] == "blob"
    assert search.data["matches"][0]["row"]["kind"] == "command"
    verify = sqlite3.connect(database)
    assert verify.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    verify.close()


def test_source_summary_dependency_map_and_symbol_trace_reduce_large_file_rounds(
    app_config: AppConfig,
) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    source = case.root / "src"
    source.mkdir()
    (source / "client.ts").write_text(
        'import axios from "axios";\n'
        'import { bridge } from "./bridge";\n'
        "export class Client {\n"
        "  sendCommand(payload: string) { return axios.post('/command', payload); }\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "bridge.ts").write_text(
        "export function bridge() { return NativeModules.CommandBridge; }\n",
        encoding="utf-8",
    )

    summary = dispatcher.execute(mcp_tool_name("summarize_source_file"), {"path": "src/client.ts"})
    dependencies = dispatcher.execute(mcp_tool_name("map_source_dependencies"), {"path": "src"})
    traced = dispatcher.execute(mcp_tool_name("trace_symbol"), {"path": "src", "symbol": "bridge"})

    assert summary.status == "completed"
    assert {item["module"] for item in summary.data["imports"]} == {"axios", "./bridge"}
    assert any(item["name"] == "Client" for item in summary.data["declarations"])
    assert summary.data["high_signal_calls"]["network"]
    assert {item["module"] for item in dependencies.data["modules"]} >= {
        "axios",
        "./bridge",
    }
    assert traced.data["returned_occurrences"] >= 2
    assert set(traced.data["classification_counts"]) & {"definition", "call_or_declaration"}


def test_compare_and_decode_static_values(app_config: AppConfig) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    (case.root / "left.js").write_text("one\ntwo\n", encoding="utf-8")
    (case.root / "right.js").write_text("one\nchanged\n", encoding="utf-8")

    compared = dispatcher.execute(
        mcp_tool_name("compare_files"),
        {"left_path": "left.js", "right_path": "right.js"},
    )
    decoded = dispatcher.execute(
        mcp_tool_name("decode_static_value"),
        {
            "value": base64.b64encode("שלום static".encode()).decode(),
            "operation": "base64",
        },
    )
    xored = dispatcher.execute(
        mcp_tool_name("decode_static_value"),
        {"value": "6968", "input_encoding": "hex", "operation": "xor", "xor_key": 1},
    )

    assert compared.status == "completed"
    assert compared.data["identical"] is False
    assert any("changed" in line for line in compared.data["diff"])
    assert decoded.data["candidates"][0]["utf8_preview"] == "שלום static"
    assert xored.data["candidates"][0]["utf8_preview"] == "hi"


def test_manifest_and_source_map_surface_android_and_original_source_context(
    app_config: AppConfig,
) -> None:
    _, case, dispatcher = make_dispatcher(app_config)
    (case.root / "AndroidManifest.xml").write_text(
        """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
          package="com.example.app" android:versionName="1.2">
          <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="35" />
          <uses-permission android:name="android.permission.INTERNET" />
          <application android:debuggable="true" android:usesCleartextTraffic="true">
            <service android:name=".CommandService" android:exported="true">
              <intent-filter><action android:name="com.example.COMMAND" /></intent-filter>
            </service>
          </application>
        </manifest>""",
        encoding="utf-8",
    )
    (case.root / "bundle.js.map").write_text(
        json.dumps(
            {
                "version": 3,
                "file": "bundle.js",
                "sources": ["src/api.ts", "../shared/bridge.ts"],
                "sourcesContent": ["export const api = 1;", "export const bridge = 2;"],
                "names": ["api", "bridge"],
                "mappings": "AAAA",
            }
        ),
        encoding="utf-8",
    )

    manifest = dispatcher.execute(
        mcp_tool_name("inspect_android_manifest"), {"path": "AndroidManifest.xml"}
    )
    source_map = dispatcher.execute(
        mcp_tool_name("inspect_source_map"),
        {
            "path": "bundle.js.map",
            "source_query": "bridge",
            "include_content": True,
        },
    )

    assert manifest.status == "completed"
    assert manifest.data["package"] == "com.example.app"
    assert manifest.data["permissions"] == ["android.permission.INTERNET"]
    assert any(
        "exported without a permission" in item for item in manifest.data["security_observations"]
    )
    assert any("debuggable" in item for item in manifest.data["security_observations"])
    assert source_map.data["matching_sources"] == 1
    assert "bridge = 2" in source_map.data["sources"][0]["content_preview"]
    assert source_map.data["suspicious_source_paths"] == ["../shared/bridge.ts"]


class CatalogClient:
    def __init__(self) -> None:
        self.calls = 0
        self.schema_names: list[set[str]] = []
        self.reasoning_level = "unlimited"
        self.max_tokens = 9999

    def set_reasoning_level(self, level: str) -> None:
        self.reasoning_level = level

    def set_max_tokens(self, value: int) -> None:
        self.max_tokens = value

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        self.calls += 1
        names = {str(item["function"]["name"]) for item in tools}
        self.schema_names.append(names)
        if self.calls == 1:
            assert mcp_tool_name("inspect_source_map") not in names
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="catalog",
                        name=mcp_tool_name("search_tool_catalog"),
                        arguments='{"query":"JavaScript source map embedded sources"}',
                    )
                ],
            )
        assert mcp_tool_name("inspect_source_map") in names
        return AssistantMessage(content="The relevant schema was loaded without the full catalog.")


def test_cli_speed_mode_caps_request_cost_and_catalog_loads_tools_next_round(
    app_config: AppConfig,
) -> None:
    manager, case, dispatcher = make_dispatcher(app_config)
    registry = dispatcher.registry
    client = CatalogClient()
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        registry,
        dispatcher,
        SessionManager(case, manager),
        speed_mode=SpeedMode.FAST,
    )

    response = agent.respond("Load one specialized capability")

    assert response == "The relevant schema was loaded without the full catalog."
    assert client.reasoning_level == "low"
    assert client.max_tokens == 1024
    assert all(len(names) <= 14 for names in client.schema_names)
    assert len(registry.schemas("generic")) > len(client.schema_names[0])
    assert mcp_tool_name("search_tool_catalog") in client.schema_names[0]
