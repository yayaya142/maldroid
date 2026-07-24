from __future__ import annotations

import base64
import bz2
import codecs
import gzip
import json
import lzma
import stat
import zlib
from urllib.parse import quote_from_bytes

import pytest

import maldroid.code_intake as code_intake_module
from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.code_intake import capture_large_fenced_code
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.llama_client import AssistantMessage, ToolCall
from maldroid.paths import PathPolicy
from maldroid.session_manager import SessionManager
from maldroid.speed import SpeedMode
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def make_dispatcher(config: AppConfig) -> tuple[Case, ToolDispatcher]:
    manager = CaseManager(config)
    case = manager.create("Code analysis")
    context = ToolContext(
        config=config,
        case=case,
        case_manager=manager,
        investigation=InvestigationManager(manager),
        path_policy=PathPolicy(case.root),
    )
    return case, ToolDispatcher(build_registry(), context)


def test_code_index_and_context_reduce_repeated_large_tree_scans(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    source = case.root / "src"
    source.mkdir()
    decoder = source / "decoder.rs"
    decoder.write_text(
        "use base64::Engine;\n"
        "pub fn decrypt_payload(value: &str) -> Vec<u8> {\n"
        "    base64::engine::general_purpose::STANDARD.decode(value).unwrap()\n"
        "}\n",
        encoding="utf-8",
    )
    minified = "let filler='" + ("x" * 12000) + "';function decryptPayload(v){return atob(v)};"
    (source / "bundle.js").write_text(minified, encoding="utf-8")

    built = dispatcher.execute(mcp_tool_name("build_code_index"), {"path": "src"})
    queried = dispatcher.execute(
        mcp_tool_name("query_code_index"),
        {"query": "decrypt_payload", "kind": "declaration"},
    )
    context = dispatcher.execute(
        mcp_tool_name("read_code_context"),
        {"path": "src/bundle.js", "symbol": "decryptPayload"},
    )
    summary = dispatcher.execute(mcp_tool_name("summarize_source_file"), {"path": "src/decoder.rs"})

    assert built.status == "completed"
    assert built.data["files_indexed"] == 2
    assert built.data["source_content_stored"] is False
    index_path = case.root / built.data["index_path"]
    assert index_path.is_file()
    assert (b"x" * 1000) not in index_path.read_bytes()
    assert b"STANDARD.decode(value).unwrap" not in index_path.read_bytes()
    assert queried.status == "completed"
    assert queried.data["results"][0]["path"] == "src/decoder.rs"
    assert queried.data["results"][0]["name"] == "decrypt_payload"
    assert context.status == "completed"
    assert "decryptPayload" in context.data["match_preview"]
    assert len(context.data["match_preview"]) < 5000
    assert context.data["whole_file_read"] is False
    assert summary.data["language"] == "Rust"
    assert summary.data["imports"][0]["module"] == "base64::Engine"

    decoder.write_text(
        decoder.read_text(encoding="utf-8") + "// changed after index\n", encoding="utf-8"
    )
    stale = dispatcher.execute(
        mcp_tool_name("query_code_index"),
        {"query": "decrypt_payload", "kind": "declaration"},
    )
    assert stale.data["stale_results"] == 1
    assert stale.data["results"][0]["stale"] is True


def test_code_index_marks_a_file_partial_when_its_entry_budget_is_exhausted(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    source = case.root / "many-symbols.py"
    source.write_text(
        "\n".join(f"def symbol_{number}(): pass" for number in range(150)),
        encoding="utf-8",
    )

    built = dispatcher.execute(
        mcp_tool_name("build_code_index"), {"path": "many-symbols.py", "max_entries": 100}
    )
    queried = dispatcher.execute(
        mcp_tool_name("query_code_index"), {"query": "symbol_0", "kind": "declaration"}
    )

    assert built.status == "completed"
    assert built.data["scan_complete"] is False
    assert built.data["truncation_reason"] == "entry_budget"
    assert queried.data["results"][0]["file_fully_indexed"] is False


def test_obfuscation_analysis_and_transform_chain_are_bounded_static_data(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    plaintext = b"https://example.test/api/v1"
    encoded = base64.b64encode(plaintext).decode()
    (case.root / "obfuscated.js").write_text(
        f'const endpoint = "{encoded}";\n'
        "const decoded = String.fromCharCode(...bytes.map(x => x ^ 0x23));\n"
        "const second = decodeURIComponent('%68%65%6c%6c%6f');\n",
        encoding="utf-8",
    )

    analysis = dispatcher.execute(
        mcp_tool_name("analyze_obfuscation"),
        {"path": "obfuscated.js", "max_candidates": 20},
    )
    compressed = gzip.compress(plaintext)
    transformed = dispatcher.execute(
        mcp_tool_name("decode_static_chain"),
        {
            "value": base64.b64encode(compressed).decode(),
            "steps": [{"operation": "base64"}, {"operation": "gzip"}],
        },
    )

    assert analysis.status == "completed"
    assert any(item["encoding"] == "base64" for item in analysis.data["candidates"])
    assert {item["signal"] for item in analysis.data["decode_signals"]} >= {
        "character-code construction",
        "URL decoding",
    }
    assert analysis.data["executed"] is False
    assert transformed.status == "completed"
    assert transformed.data["final"]["utf8_preview"] == plaintext.decode()
    assert [item["operation"] for item in transformed.data["provenance"]] == [
        "base64",
        "gzip",
    ]
    assert transformed.data["executed"] is False


def test_transform_chain_rejects_decompression_expansion(app_config: AppConfig) -> None:
    _, dispatcher = make_dispatcher(app_config)
    compressed = gzip.compress(b"A" * (2 * 1024 * 1024 + 1))

    result = dispatcher.execute(
        mcp_tool_name("decode_static_chain"),
        {
            "value": base64.b64encode(compressed).decode(),
            "steps": [{"operation": "base64"}, {"operation": "gzip"}],
        },
    )

    assert result.status == "error"
    assert "output limit" in result.error.message.lower()


@pytest.mark.parametrize(
    ("operation", "value", "input_encoding", "key"),
    [
        ("base32", base64.b32encode(b"hello transform").decode(), "text", None),
        ("hex", b"hello transform".hex(), "text", None),
        ("url", quote_from_bytes(b"hello transform"), "text", None),
        ("unicode_escape", r"hello\u0020transform", "text", None),
        ("rot13", codecs.encode("hello transform", "rot_13"), "text", None),
        ("reverse", "mrofsnart olleh", "text", None),
        ("xor", bytes(byte ^ 1 for byte in b"hello transform").hex(), "hex", 1),
        ("add", bytes((byte - 1) & 0xFF for byte in b"hello transform").hex(), "hex", 1),
        ("subtract", bytes((byte + 1) & 0xFF for byte in b"hello transform").hex(), "hex", 1),
        (
            "rotate_left",
            bytes(((byte >> 1) | (byte << 7)) & 0xFF for byte in b"hello transform").hex(),
            "hex",
            1,
        ),
        (
            "rotate_right",
            bytes(((byte << 1) | (byte >> 7)) & 0xFF for byte in b"hello transform").hex(),
            "hex",
            1,
        ),
        ("gzip", base64.b64encode(gzip.compress(b"hello transform")).decode(), "base64", None),
        ("zlib", base64.b64encode(zlib.compress(b"hello transform")).decode(), "base64", None),
        ("bz2", base64.b64encode(bz2.compress(b"hello transform")).decode(), "base64", None),
        ("lzma", base64.b64encode(lzma.compress(b"hello transform")).decode(), "base64", None),
    ],
)
def test_supported_static_transforms_preserve_bounded_provenance(
    app_config: AppConfig,
    operation: str,
    value: str,
    input_encoding: str,
    key: int | None,
) -> None:
    _, dispatcher = make_dispatcher(app_config)
    step: dict[str, object] = {"operation": operation}
    if key is not None:
        step["key"] = key

    result = dispatcher.execute(
        mcp_tool_name("decode_static_chain"),
        {"value": value, "input_encoding": input_encoding, "steps": [step]},
    )

    assert result.status == "completed"
    assert result.data["final"]["utf8_preview"] == "hello transform"
    assert result.data["provenance"][0]["operation"] == operation
    assert result.data["provenance"][0]["output_sha256"] == result.data["final"]["sha256"]
    assert result.data["executed"] is False


def test_python_decoder_is_prepared_with_provenance_but_never_executed(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    side_effect = case.root / "MUST_NOT_EXIST"
    source = (
        "import base64\n"
        "from pathlib import Path\n\n"
        "def main() -> None:\n"
        "    Path('MUST_NOT_EXIST').write_text(base64.b64decode('aGk=').decode())\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    prepared = dispatcher.execute(
        mcp_tool_name("write_python_script"),
        {
            "name": "decode-config",
            "objective": "Decode the recovered Base64 configuration without executing evidence",
            "source": source,
            "inputs": ["evidence/config.dat"],
            "expected_outputs": ["workspace/decoded-config.bin"],
            "related_state_ids": ["TODO-0001"],
        },
    )

    assert prepared.status == "completed"
    assert prepared.data["prepared"] is True
    assert prepared.data["execution_status"] == "not_executed"
    assert prepared.data["script_id"] == "SCRIPT-0001"
    assert prepared.data["diff"].startswith("--- /dev/null")
    script_path = case.root / prepared.data["path"]
    manifest_path = case.root / prepared.data["manifest_path"]
    assert script_path.is_file()
    assert manifest_path.is_file()
    assert not list(script_path.parent.glob("*.lock"))
    assert stat.S_IMODE(script_path.stat().st_mode) == 0o600
    assert not side_effect.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == prepared.data["source_sha256"]
    assert manifest["execution"]["status"] == "not_executed"
    assert manifest["execution"]["exit_code"] is None
    assert manifest["approval_mode"] == "review_only"
    assert manifest["prepared_in_virtual_environment"] is True
    assert {item["import"] for item in manifest["packages"]} == {"base64", "pathlib"}
    assert {item["distribution"] for item in manifest["packages"]} == {"stdlib"}

    second = dispatcher.execute(
        mcp_tool_name("write_python_script"),
        {"name": "decode-config", "objective": "Revision", "source": "print('review')\n"},
    )
    listed = dispatcher.execute(mcp_tool_name("list_python_scripts"), {})
    assert second.data["script_id"] == "SCRIPT-0002"
    assert second.data["path"] != prepared.data["path"]
    assert listed.data["script_count"] == 2
    assert {item["execution_status"] for item in listed.data["scripts"]} == {"not_executed"}


def test_script_listing_never_follows_manifest_symlinks(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    scripts = case.root / "workspace" / "scripts"
    scripts.mkdir()
    outside = case.root.parent / "outside-manifest.json"
    outside.write_text('{"objective": "host secret"}', encoding="utf-8")
    (scripts / "SCRIPT-9999-escape.json").symlink_to(outside)

    listed = dispatcher.execute(mcp_tool_name("list_python_scripts"), {})

    assert listed.status == "completed"
    assert listed.data["invalid_manifests"] == 1
    assert "host secret" not in json.dumps(listed.data)


def test_python_script_writer_rejects_active_process_or_network_capabilities(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)

    dangerous_sources = {
        "subprocess": "import subprocess\nsubprocess.run(['id'])\n",
        "network": "from urllib import request\nrequest.urlopen('https://example.test')\n",
        "dynamic": "payload = 'print(1)'\neval(payload)\n",
        "host-secrets": "import os\nprint(os.environ)\n",
        "absolute-path": "from pathlib import Path\nPath('/etc/passwd').read_text()\n",
    }
    for name, source in dangerous_sources.items():
        rejected = dispatcher.execute(
            mcp_tool_name("write_python_script"),
            {
                "name": f"unsafe-{name}",
                "objective": "Should be rejected",
                "source": source,
            },
        )
        assert rejected.status == "completed"
        assert rejected.data["prepared"] is False
        assert rejected.data["risk_level"] == "blocked"
        assert rejected.data["risk_findings"]
    assert not list((case.root / "workspace" / "scripts").glob("*.py"))


def test_python_script_writer_reports_syntax_location_without_writing(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)

    result = dispatcher.execute(
        mcp_tool_name("write_python_script"),
        {"name": "broken", "objective": "Validate first", "source": "def broken(:\n    pass\n"},
    )

    assert result.status == "error"
    assert "line 1" in result.error.message
    assert not list((case.root / "workspace" / "scripts").glob("*.py"))


def test_script_directory_symlink_cannot_escape_case(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    outside = case.root.parent / "outside"
    outside.mkdir()
    (case.root / "workspace" / "scripts").symlink_to(outside, target_is_directory=True)

    result = dispatcher.execute(
        mcp_tool_name("write_python_script"),
        {"name": "escape", "objective": "Stay local", "source": "print('safe')\n"},
    )

    assert result.status == "error"
    assert "symbolic link" in result.error.message.lower()
    assert list(outside.iterdir()) == []


def test_script_provenance_paths_must_remain_case_relative(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)

    result = dispatcher.execute(
        mcp_tool_name("write_python_script"),
        {
            "name": "bad-provenance",
            "objective": "Do not escape",
            "source": "print('review')\n",
            "inputs": ["../../etc/passwd"],
        },
    )

    assert result.status == "error"
    assert result.error.code == "invalid_arguments"
    assert "case-relative" in result.error.message
    assert not list((case.root / "workspace" / "scripts").glob("*.py"))


def test_registry_never_exposes_python_execution(app_config: AppConfig) -> None:
    registry = build_registry()
    names = set(registry.names("generic"))

    assert mcp_tool_name("write_python_script") in names
    assert mcp_tool_name("list_python_scripts") in names
    assert mcp_tool_name("run_python_script") not in names
    write_schema = next(
        item
        for item in registry.schemas("generic")
        if item["function"]["name"] == mcp_tool_name("write_python_script")
    )
    source_description = write_schema["function"]["parameters"]["properties"]["source"][
        "description"
    ]
    assert "without executing" in source_description


def test_code_index_does_not_follow_nested_source_symlinks(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    source = case.root / "src"
    source.mkdir()
    (source / "inside.py").write_text("def inside_symbol():\n    pass\n", encoding="utf-8")
    outside = case.root.parent / "outside.py"
    outside.write_text("def outside_secret_symbol():\n    pass\n", encoding="utf-8")
    (source / "outside.py").symlink_to(outside)

    built = dispatcher.execute(mcp_tool_name("build_code_index"), {"path": "src"})
    queried = dispatcher.execute(
        mcp_tool_name("query_code_index"), {"query": "outside_secret_symbol"}
    )

    assert built.status == "completed"
    assert built.data["files_indexed"] == 1
    assert queried.data["total_matches"] == 0


def test_code_index_output_cannot_escape_through_symlink(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.py").write_text("def sample():\n    pass\n", encoding="utf-8")
    indexes = case.internal / "indexes"
    indexes.rmdir()
    outside = case.root.parent / "outside-index"
    outside.mkdir()
    indexes.symlink_to(outside, target_is_directory=True)

    result = dispatcher.execute(mcp_tool_name("build_code_index"), {"path": "sample.py"})

    assert result.status == "error"
    assert "symbolic link" in result.error.message.lower()
    assert list(outside.iterdir()) == []


def test_large_code_capture_rejects_symlinked_output_directory(app_config: AppConfig) -> None:
    case, _ = make_dispatcher(app_config)
    outside = case.root.parent / "outside-snippets"
    outside.mkdir()
    (case.root / "workspace" / "snippets").symlink_to(outside, target_is_directory=True)
    code = "A" * 9000

    with pytest.raises(ValueError, match="symbolic link"):
        capture_large_fenced_code(case, f"```javascript\n{code}\n```")

    assert list(outside.iterdir()) == []


def test_large_code_capture_enforces_its_limit_in_utf8_bytes(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, _ = make_dispatcher(app_config)
    code = "שלום" * 2500
    assert len(code) >= code_intake_module.MINIMUM_CAPTURE_CHARACTERS
    monkeypatch.setattr(code_intake_module, "MAXIMUM_CAPTURE_BYTES", len(code.encode("utf-8")) - 1)

    with pytest.raises(ValueError, match="64 MiB capture limit"):
        capture_large_fenced_code(case, f"```text\n{code}\n```")

    assert not (case.root / "workspace" / "snippets").exists()


def test_large_fenced_code_is_captured_exactly_and_replaced_with_a_bounded_reference(
    app_config: AppConfig,
) -> None:
    case, dispatcher = make_dispatcher(app_config)
    manager = dispatcher.context.case_manager
    events: list[tuple[str, dict]] = []

    class CaptureClient:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        def set_reasoning_level(self, level: str) -> None:
            pass

        def set_max_tokens(self, value: int) -> None:
            pass

        def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
            self.messages = messages
            return AssistantMessage(content="Captured code is ready for bounded inspection.")

    code = "const hidden = '" + ("A" * 9000) + "';"
    client = CaptureClient()
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        dispatcher.registry,
        dispatcher,
        sessions,
        event_handler=lambda event, data: events.append((event, data)),
        speed_mode=SpeedMode.FAST,
    )

    response = agent.respond(
        f"Analyze this complete bundle:\n```javascript\n{code}\n```\nFind the decoder."
    )

    assert response.startswith("Captured code")
    snippet = next((case.root / "workspace" / "snippets").glob("SNIPPET-*.js"))
    assert snippet.read_text(encoding="utf-8") == code
    assert not list(snippet.parent.glob("*.lock"))
    model_message = next(item for item in client.messages if item.get("role") == "user")
    assert "workspace/snippets/" in model_message["content"]
    assert code not in model_message["content"]
    assert "untrusted" in model_message["content"].lower()
    history = sessions.history_path.read_text(encoding="utf-8")
    assert code not in history
    captured = next(data for event, data in events if event == "code_snippet_captured")
    assert captured["path"].startswith("workspace/snippets/SNIPPET-")
    assert captured["characters"] == len(code)


def test_fast_mode_keeps_objective_slots_for_obfuscation_tools(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)

    class SchemaClient:
        def __init__(self) -> None:
            self.names: set[str] = set()

        def set_reasoning_level(self, level: str) -> None:
            pass

        def set_max_tokens(self, value: int) -> None:
            pass

        def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
            self.names = {str(item["function"]["name"]) for item in tools}
            return AssistantMessage(content="Ready.")

    client = SchemaClient()
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        dispatcher.registry,
        dispatcher,
        SessionManager(case, dispatcher.context.case_manager),
        speed_mode=SpeedMode.FAST,
    )

    agent.respond("Analyze this obfuscated encrypted source and prepare a Python decoder script")

    assert len(client.names) <= 14
    assert mcp_tool_name("analyze_obfuscation") in client.names
    assert mcp_tool_name("write_python_script") in client.names


def test_agent_guarantees_prepared_not_executed_disclosure(app_config: AppConfig) -> None:
    case, dispatcher = make_dispatcher(app_config)
    events: list[tuple[str, dict]] = []

    class ScriptClient:
        def __init__(self) -> None:
            self.calls = 0

        def set_reasoning_level(self, level: str) -> None:
            pass

        def set_max_tokens(self, value: int) -> None:
            pass

        def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
            self.calls += 1
            if self.calls == 1:
                return AssistantMessage(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="script",
                            name=mcp_tool_name("write_python_script"),
                            arguments=json.dumps(
                                {
                                    "name": "decode-token",
                                    "objective": "Decode the recovered token",
                                    "source": "import base64\nprint(base64.b64decode('aGk='))\n",
                                }
                            ),
                        )
                    ],
                )
            return AssistantMessage(content="I prepared the requested helper.")

    agent = MalDroidAgent(
        app_config,
        case,
        ScriptClient(),
        dispatcher.registry,
        dispatcher,
        SessionManager(case, dispatcher.context.case_manager),
        event_handler=lambda event, data: events.append((event, data)),
        speed_mode=SpeedMode.FAST,
    )

    response = agent.respond("Prepare a Python decoder for this value")

    assert "not executed by MalDroid" in response
    assert "workspace/scripts/SCRIPT-0001-decode-token.py" in response
    script_result = next(
        data
        for event, data in events
        if event == "tool_result" and data.get("name") == mcp_tool_name("write_python_script")
    )
    assert script_result["prepared_path"].endswith("SCRIPT-0001-decode-token.py")
    assert script_result["execution_status"] == "not_executed"
