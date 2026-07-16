from __future__ import annotations

import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from maldroid.agent import STATE_DISCIPLINE_REMINDER, MalDroidAgent
from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.evidence_manager import EvidenceManager
from maldroid.exceptions import TurnCancelledError
from maldroid.investigation import InvestigationManager
from maldroid.knowledge_manager import KnowledgeManager
from maldroid.llama_client import (
    AssistantMessage,
    RepetitionMatch,
    RepetitiveGenerationError,
    ToolCall,
)
from maldroid.paths import PathPolicy
from maldroid.prompts import SYSTEM_PROMPT
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import MCP_TOOL_PREFIX, ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry


def make_dispatcher(app_config: AppConfig):
    manager = CaseManager(app_config)
    case = manager.create()
    investigation = InvestigationManager(manager)
    registry = build_registry()
    context = ToolContext(
        config=app_config,
        case=case,
        case_manager=manager,
        investigation=investigation,
        path_policy=PathPolicy(case.root),
    )
    return manager, case, registry, ToolDispatcher(registry, context)


def test_save_finding_accepts_evidence_without_description_and_persists_views(
    app_config: AppConfig,
) -> None:
    manager, case, _, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("first\nsecond\n", encoding="utf-8")

    result = dispatcher.execute(
        mcp_tool_name("save_finding"),
        {
            "title": "Endpoint discovered",
            "summary": "The sample contains a candidate endpoint.",
            "confidence": "high",
            "severity": "informational",
            "status": "confirmed",
            "evidence": [{"path": "sample.txt", "start_line": 2, "end_line": 2}],
            "tags": ["network"],
        },
    )

    assert result.status == "completed"
    reopened = manager.open(case.root)
    assert reopened.state.findings[0].evidence[0].description == "Supporting evidence"
    rendered = (case.root / "notes" / "FINDINGS.md").read_text(encoding="utf-8")
    assert "`sample.txt:2`" in rendered
    assert "network" in rendered


def test_failed_finding_view_write_rolls_back_canonical_state(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, case, _, dispatcher = make_dispatcher(app_config)

    def fail_views(_case: object) -> None:
        raise OSError("read-only notes folder")

    monkeypatch.setattr(InvestigationManager, "_render_views", fail_views)
    result = dispatcher.execute(
        mcp_tool_name("save_finding"),
        {"title": "Will fail", "summary": "This mutation must be rolled back."},
    )

    assert result.status == "error"
    assert case.state.findings == []
    assert manager.open(case.root).state.findings == []


def test_typed_checkpoint_and_complete_state_readback(app_config: AppConfig) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    saved = dispatcher.execute(
        mcp_tool_name("save_checkpoint"),
        {
            "objective": "Trace the registration flow",
            "completed_work": ["Mapped the request builder"],
            "evidence_learned": ["Registration sends the device identifier"],
            "unresolved_questions": ["Which caller supplies the endpoint?"],
            "next_action": "Trace callers of registerDevice",
        },
    )

    assert saved.status == "completed"
    assert case.state.notes == []
    assert case.state.checkpoints[0].id == "CHECK-0001"
    rendered = (case.root / "notes" / "CHECKPOINTS.md").read_text(encoding="utf-8")
    assert "Registration sends the device identifier" in rendered
    assert "Trace callers of registerDevice" in rendered

    state = dispatcher.execute(mcp_tool_name("read_case_state"), {})
    assert state.data["counts"]["checkpoints"] == 1
    assert state.data["latest_checkpoint"]["id"] == "CHECK-0001"
    listed = dispatcher.execute(mcp_tool_name("list_checkpoints"), {"page_size": 10})
    assert listed.data["records"][0]["objective"] == "Trace the registration flow"


def test_checkpoint_rejects_operationally_empty_payload(app_config: AppConfig) -> None:
    _, _, _, dispatcher = make_dispatcher(app_config)
    result = dispatcher.execute(
        mcp_tool_name("save_checkpoint"),
        {"objective": "Keep going", "next_action": "Call another tool"},
    )
    assert result.status == "error"
    assert "substantive research progress" in result.error.message


def test_research_note_rejects_tool_activity_but_user_note_remains_free(
    app_config: AppConfig,
) -> None:
    manager, case, _, dispatcher = make_dispatcher(app_config)
    rejected = dispatcher.execute(
        mcp_tool_name("save_note"),
        {"text": 'Tool result: {"tool":"MalDroid_search_text","status":"error"}'},
    )

    assert rejected.status == "error"
    assert "tool activity and errors belong in the session audit" in rejected.error.message
    assert case.state.notes == []

    note = InvestigationManager(manager).save_note(case, "quick human marker", kind="user_note")
    assert note.kind == "user_note"


def test_documented_system_prompt_matches_runtime_prompt() -> None:
    document = (Path(__file__).resolve().parents[1] / "SYSTEM_PROMPT.md").read_text(
        encoding="utf-8"
    )
    assert SYSTEM_PROMPT.strip() in document
    assert "MalDroid_read_case_state, then MalDroid_list_case_files" in SYSTEM_PROMPT


def test_registry_profile_filtering(app_config: AppConfig) -> None:
    _, _, registry, _ = make_dispatcher(app_config)
    generic = set(registry.names("generic"))
    react_native = set(registry.names("react-native"))
    assert mcp_tool_name("read_file_range") in generic
    assert mcp_tool_name("inspect_javascript_bundle") not in generic
    assert generic < react_native
    assert all(name.startswith(MCP_TOOL_PREFIX) for name in react_native)
    assert not any("flutter" in name or "unity" in name for name in generic)


@pytest.mark.parametrize(
    ("profile", "marker"),
    [
        ("react-native", "React Native Investigation Methodology"),
        ("native", "Native and Ghidra MCP Investigation Methodology"),
    ],
)
def test_agent_routes_profile_methodology_into_context(
    app_config: AppConfig, profile: str, marker: str
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    case.state.active_profile = profile
    manager.save(case)
    agent = MalDroidAgent(
        app_config,
        case,
        FakeClient(),
        registry,
        dispatcher,
        SessionManager(case, manager),
        auto_profile_enabled=False,
    )

    methodology = "\n".join(
        str(message.get("content", ""))
        for message in agent.messages
        if message.get("role") == "system"
    )
    assert marker in methodology


def test_dispatcher_executes_and_rejects_profile_tool(app_config: AppConfig) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    sample = case.root / "sample.txt"
    sample.write_text("one\nneedle\nthree\n", encoding="utf-8")
    result = dispatcher.execute(
        mcp_tool_name("read_file_range"),
        {"path": "sample.txt", "start_line": 2, "end_line": 2},
    )
    assert result.status == "completed"
    assert result.data["lines"][0]["text"] == "needle"
    disabled = dispatcher.execute(
        mcp_tool_name("inspect_javascript_bundle"), {"path": "sample.txt"}
    )
    assert disabled.error and disabled.error.code == "disabled_tool"
    invalid = dispatcher.execute(mcp_tool_name("read_file_range"), "not-json")
    assert invalid.error and invalid.error.code == "invalid_json"
    unprefixed = dispatcher.execute("read_file_range", {})
    assert unprefixed.error and unprefixed.error.code == "unknown_tool"


def test_dispatcher_saves_oversized_output(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["limits"]["max_tool_output_characters"] = 1000
    limited = AppConfig.model_validate(data)
    _, case, _, dispatcher = make_dispatcher(limited)
    sample = case.root / "large-line.txt"
    sample.write_text("x" * 5000 + "\n", encoding="utf-8")
    result = dispatcher.execute(
        mcp_tool_name("read_file_range"),
        {"path": sample.name, "start_line": 1, "end_line": 1},
    )
    assert result.truncated is True
    assert result.output_file
    assert (case.root / result.output_file).is_file()


def test_python_search_fallback_skips_nested_symlinks(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("DO_NOT_SCAN_OUTSIDE_CASE", encoding="utf-8")
    (case.root / "nested-link.txt").symlink_to(outside)
    monkeypatch.setattr("maldroid.tools.core.builtin.shutil.which", lambda _: None)

    result = dispatcher.execute(
        mcp_tool_name("search_text"),
        {"path": ".", "query": "DO_NOT_SCAN_OUTSIDE_CASE"},
    )

    assert result.status == "completed"
    assert result.data["total_matches"] == 0


def test_python_search_fallback_handles_a_multi_megabyte_minified_line(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    sample = case.root / "minified.js"
    sample.write_text("x" * (2 * 1024 * 1024) + "BOUNDARY_TOKEN", encoding="utf-8")
    monkeypatch.setattr("maldroid.tools.core.builtin.shutil.which", lambda _: None)

    result = dispatcher.execute(
        mcp_tool_name("search_text"),
        {"path": sample.name, "query": "BOUNDARY_TOKEN"},
    )

    assert result.status == "completed"
    assert result.data["total_matches"] == 1
    assert result.data["results"][0]["line"] == 1
    assert "BOUNDARY_TOKEN" in result.data["results"][0]["preview"]
    assert len(result.data["results"][0]["preview"]) <= 1000


def test_text_range_bounds_a_multi_megabyte_logical_line(app_config: AppConfig) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    sample = case.root / "huge-minified.js"
    sample.write_text("A" * (2 * 1024 * 1024), encoding="utf-8")

    result = dispatcher.execute(
        mcp_tool_name("read_file_range"),
        {"path": sample.name, "start_line": 1, "end_line": 1},
    )

    assert result.status == "completed"
    assert result.data["returned_lines"] == 1
    assert result.data["lines"][0]["truncated"] is True
    assert len(result.data["lines"][0]["text"]) == 4000
    assert result.data["content_truncated"] is True


def test_ripgrep_search_stops_after_the_global_result_budget(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["limits"]["max_search_results"] = 3
    limited = AppConfig.model_validate(data)
    _, case, _, dispatcher = make_dispatcher(limited)
    (case.root / "many.txt").write_text(
        "".join(f"needle {number}\n" for number in range(20)), encoding="utf-8"
    )

    result = dispatcher.execute(
        mcp_tool_name("search_text"),
        {"path": ".", "query": "needle", "page_size": 3},
    )

    assert result.status == "completed"
    assert result.data["bounded_matches"] == 3
    assert result.data["total_matches"] == 4
    assert result.data["total_matches_exact"] is False
    assert result.data["truncated"] is True


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep is not installed")
def test_ripgrep_search_preserves_a_filename_containing_a_newline(app_config: AppConfig) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    unusual = case.root / "line\nbreak.txt"
    unusual.write_text("UNUSUAL_PATH_MATCH\n", encoding="utf-8")

    result = dispatcher.execute(
        mcp_tool_name("search_text"),
        {"path": ".", "query": "UNUSUAL_PATH_MATCH"},
    )

    assert result.status == "completed"
    assert result.data["total_matches"] == 1
    assert result.data["results"][0]["path"] == unusual.name


def test_search_skips_generated_outputs_broadly_but_allows_an_explicit_output(
    app_config: AppConfig,
) -> None:
    _, case, _, dispatcher = make_dispatcher(app_config)
    output = case.root / "tool-output" / "explicit-search.txt"
    output.write_text("EXPLICIT_GENERATED_RESULT\n", encoding="utf-8")

    broad = dispatcher.execute(
        mcp_tool_name("search_text"),
        {"path": ".", "query": "EXPLICIT_GENERATED_RESULT"},
    )
    explicit = dispatcher.execute(
        mcp_tool_name("search_text"),
        {"path": "tool-output/explicit-search.txt", "query": "EXPLICIT_GENERATED_RESULT"},
    )

    assert broad.status == "completed"
    assert broad.data["total_matches"] == 0
    assert explicit.status == "completed"
    assert explicit.data["total_matches"] == 1


def test_register_evidence_refreshes_the_live_path_policy(
    app_config: AppConfig, tmp_path: Path
) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    source = tmp_path / "registered.txt"
    source.write_text("registered evidence", encoding="utf-8")
    first = EvidenceManager(manager).register(case, source)
    investigation = InvestigationManager(manager)
    registry = build_registry()
    context = ToolContext(
        config=app_config,
        case=case,
        case_manager=manager,
        investigation=investigation,
        path_policy=PathPolicy(
            case.root,
            {first.case_path: first.source_resolved_path},
        ),
    )
    dispatcher = ToolDispatcher(registry, context)

    registered = dispatcher.execute(
        mcp_tool_name("register_evidence"),
        {"path": first.case_path, "mode": "symlink"},
    )
    second_path = registered.data["case_path"]
    readback = dispatcher.execute(
        mcp_tool_name("read_file_range"),
        {"path": second_path, "start_line": 1, "end_line": 1},
    )

    assert registered.status == "completed"
    assert readback.status == "completed"
    assert readback.data["lines"][0]["text"] == "registered evidence"


def test_evidence_registration_rolls_back_when_case_save_fails(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = CaseManager(app_config)
    case = manager.create()
    source = tmp_path / "rollback.txt"
    source.write_text("must not be orphaned", encoding="utf-8")

    def fail_save(_case: object) -> None:
        raise OSError("simulated persistence failure")

    monkeypatch.setattr(manager, "save", fail_save)
    with pytest.raises(OSError, match="persistence failure"):
        EvidenceManager(manager).register(case, source, "copy")

    assert case.state.evidence == []
    assert list((case.root / "evidence").iterdir()) == []


def test_builtin_knowledge_reindex_search_and_bounded_read(app_config: AppConfig) -> None:
    manager, case, _, _ = make_dispatcher(app_config)
    knowledge = KnowledgeManager(case)
    indexed = knowledge.reindex()
    assert indexed["documents"] >= 10
    matches = knowledge.search("Metro bundle", "react-native")
    assert matches
    excerpt = knowledge.read_range(matches[0]["document_key"], 1, 8)
    assert excerpt["lines"]


def test_knowledge_reindex_namespaces_colliding_root_paths(
    app_config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, case, _, _ = make_dispatcher(app_config)
    roots = [tmp_path / name / "knowledge" for name in ("builtin", "user", "case")]
    for index, root in enumerate(roots, 1):
        document = root / "generic" / "shared.md"
        document.parent.mkdir(parents=True)
        document.write_text(f"# Shared {index}\n\nunique-{index}\n", encoding="utf-8")
    knowledge = KnowledgeManager(case)
    monkeypatch.setattr(knowledge, "roots", lambda: roots)

    indexed = knowledge.reindex()
    keys = {item["document_key"] for item in knowledge.list_documents()}

    assert indexed == {"documents": 3}
    assert keys == {
        "builtin/generic/shared.md",
        "user/generic/shared.md",
        "case/generic/shared.md",
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    def complete(self, messages, tools):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                reasoning_content="bounded reasoning",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name=mcp_tool_name("read_case_state"),
                        arguments="{}",
                    )
                ],
            )
        return AssistantMessage(content="Investigation state inspected.")


def test_agent_cancellation_preserves_state_and_marks_objective_stopped(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)

    class BlockingClient:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.cancelled = threading.Event()

        def reset_cancellation(self) -> None:
            self.cancelled.clear()

        def cancel_current(self) -> None:
            self.cancelled.set()

        def complete(self, messages, tools):
            self.started.set()
            self.cancelled.wait(2)
            raise TurnCancelledError("Turn stopped by user.")

    client = BlockingClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.respond, "Trace the registration flow")
        assert client.started.wait(1)
        agent.cancel_turn()
        with pytest.raises(TurnCancelledError, match="stopped by user"):
            future.result(timeout=2)

    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    cancelled = next(event for event in events if event["type"] == "turn_cancelled")
    assert cancelled["content"]["objective"] == "Trace the registration flow"
    assert case.state.findings == []
    assert "Do not continue that objective" in str(agent.messages[-1]["content"])


def test_agent_tool_call_round_trip(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    client = FakeClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)
    response = agent.respond("Inspect current state")
    assert response == "Investigation state inspected."
    assert client.calls == 2
    assert any(message.get("role") == "tool" for message in client.messages)
    assistant = next(message for message in client.messages if message.get("role") == "assistant")
    assert assistant["reasoning_content"] == "bounded reasoning"
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    assert {event["type"] for event in events} >= {"tool_call", "tool_result"}


def test_agent_auto_selects_profile_and_refreshes_available_tools(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "index.android.bundle").write_text(
        "__d(function(){return HermesInternal;},1,[]);",
        encoding="utf-8",
    )
    sessions = SessionManager(case, manager)

    class ProfileAwareClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            names = {item["function"]["name"] for item in tools}
            assert mcp_tool_name("inspect_javascript_bundle") in names
            return AssistantMessage(content="React Native profile selected automatically.")

    agent = MalDroidAgent(
        app_config,
        case,
        ProfileAwareClient(),
        registry,
        dispatcher,
        sessions,
    )

    response = agent.respond("Analyze the supplied artifact")

    assert response == "React Native profile selected automatically."
    assert case.state.active_profile == "react-native"
    assert agent.profile_mode == "auto"
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    change = next(event for event in events if event["type"] == "profile_change")
    assert change["content"]["mode"] == "auto"


def test_agent_reuses_profile_detection_until_evidence_changes(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    original_execute = dispatcher.execute
    detections = 0

    def counting_execute(name, arguments):
        nonlocal detections
        if name == mcp_tool_name("detect_profile"):
            detections += 1
        return original_execute(name, arguments)

    monkeypatch.setattr(dispatcher, "execute", counting_execute)

    class TwoAnswerClient:
        @staticmethod
        def complete(messages, tools):
            return AssistantMessage(content="Done.")

    agent = MalDroidAgent(
        app_config,
        case,
        TwoAnswerClient(),
        registry,
        dispatcher,
        sessions,
    )

    assert agent.respond("First question") == "Done."
    assert agent.respond("Second question") == "Done."
    assert detections == 1


def test_manual_profile_override_stays_locked_until_auto_is_enabled(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "index.android.bundle").write_text("__d(function(){},1,[]);", encoding="utf-8")
    sessions = SessionManager(case, manager)

    class ManualProfileClient:
        @staticmethod
        def complete(messages, tools):
            names = {item["function"]["name"] for item in tools}
            assert mcp_tool_name("inspect_elf_file") in names
            assert mcp_tool_name("inspect_javascript_bundle") not in names
            assert mcp_tool_name("select_profile") not in names
            return AssistantMessage(content="Manual profile preserved.")

    agent = MalDroidAgent(
        app_config,
        case,
        ManualProfileClient(),
        registry,
        dispatcher,
        sessions,
    )
    agent.switch_profile("native", automatic=False)

    assert agent.respond("Keep the forced profile") == "Manual profile preserved."
    assert case.state.active_profile == "native"
    assert agent.profile_mode == "manual"

    agent.enable_auto_profile()
    assert case.state.active_profile == "react-native"
    assert agent.profile_mode == "auto"


def test_manual_profile_lock_survives_model_requested_detection(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "index.android.bundle").write_text("__d(function(){},1,[]);", encoding="utf-8")
    sessions = SessionManager(case, manager)

    class DetectingClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AssistantMessage(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="detect-profile",
                            name=mcp_tool_name("detect_profile"),
                            arguments='{"path":"."}',
                        )
                    ],
                )
            names = {item["function"]["name"] for item in tools}
            assert mcp_tool_name("inspect_elf_file") in names
            assert mcp_tool_name("inspect_javascript_bundle") not in names
            return AssistantMessage(content="Manual Native profile remained locked.")

    agent = MalDroidAgent(
        app_config,
        case,
        DetectingClient(),
        registry,
        dispatcher,
        sessions,
    )
    agent.switch_profile("native", automatic=False)

    assert agent.respond("Keep Native locked while checking the evidence") == (
        "Manual Native profile remained locked."
    )
    assert case.state.active_profile == "native"
    assert agent.profile_mode == "manual"


def test_failed_automatic_profile_detection_is_retried(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    original_execute = dispatcher.execute
    detections = 0

    def intermittently_failing_execute(name, arguments):
        nonlocal detections
        if name == mcp_tool_name("detect_profile"):
            detections += 1
            if detections == 1:
                from maldroid.models import ToolError, ToolResult

                return ToolResult(
                    status="error",
                    error=ToolError(code="temporary_failure", message="temporary detector error"),
                )
        return original_execute(name, arguments)

    monkeypatch.setattr(dispatcher, "execute", intermittently_failing_execute)

    class AnswerClient:
        @staticmethod
        def complete(messages, tools):
            return AssistantMessage(content="Done.")

    agent = MalDroidAgent(
        app_config,
        case,
        AnswerClient(),
        registry,
        dispatcher,
        sessions,
    )

    assert agent.respond("First") == "Done."
    assert agent.respond("Second") == "Done."
    assert detections == 2


def test_model_can_select_profile_from_evidence_when_auto_detection_is_ambiguous(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "ambiguous.dat").write_bytes(b"framework-specific fixture")
    sessions = SessionManager(case, manager)

    class SelectingClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            names = {item["function"]["name"] for item in tools}
            if self.calls == 1:
                assert mcp_tool_name("select_profile") in names
                return AssistantMessage(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="select-unity",
                            name=mcp_tool_name("select_profile"),
                            arguments=(
                                '{"profile":"unity","confidence":"medium",'
                                '"reason":"Concrete IL2CPP metadata indicators were inspected."}'
                            ),
                        )
                    ],
                )
            assert mcp_tool_name("detect_unity_backend") in names
            return AssistantMessage(content="Unity analysis tools are now active.")

    agent = MalDroidAgent(
        app_config,
        case,
        SelectingClient(),
        registry,
        dispatcher,
        sessions,
    )

    response = agent.respond("Choose the correct framework tools")

    assert response == "Unity analysis tools are now active."
    assert case.state.active_profile == "unity"


def test_agent_reports_live_model_and_tool_events(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    reported: list[tuple[str, dict]] = []
    agent = MalDroidAgent(
        app_config,
        case,
        FakeClient(),
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, data: reported.append((event, data)),
    )

    agent.respond("Inspect current state")

    assert [event for event, _ in reported].count("model_start") == 2
    assert any(event == "tool_start" for event, _ in reported)
    result = next(data for event, data in reported if event == "tool_result")
    assert result["name"] == "MalDroid_read_case_state"
    assert result["status"] == "completed"


def test_agent_redirects_an_identical_tool_result_loop(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)

    class LoopThenAnswerClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls <= 3:
                return AssistantMessage(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id=f"same-{self.calls}",
                            name=mcp_tool_name("read_case_state"),
                            arguments="{}",
                        )
                    ],
                )
            assert any(
                "same tool call returned the same result" in str(item.get("content", ""))
                for item in messages
            )
            return AssistantMessage(content="Changed strategy and completed.")

    client = LoopThenAnswerClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)

    assert agent.respond("Inspect without looping") == "Changed strategy and completed."
    assert client.calls == 4


def test_agent_stops_a_persistent_identical_tool_result_loop(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("stable", encoding="utf-8")
    sessions = SessionManager(case, manager)
    reported: list[tuple[str, dict]] = []

    class LoopingClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=f"same-{self.calls}",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )

    client = LoopingClient()
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, data: reported.append((event, data)),
    )

    response = agent.respond("Inspect without looping forever")

    assert "repeated the same unchanged tool result" in response
    assert client.calls == 5
    assert any(event == "tool_loop_stopped" for event, _ in reported)
    assert case.state.checkpoints == []


def test_shutdown_summary_preserves_prior_synthesis_without_recursive_growth(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    case.state.summary = "Valuable prior synthesis."
    manager.save(case)
    agent = MalDroidAgent(
        app_config,
        case,
        FakeClient(),
        registry,
        dispatcher,
        SessionManager(case, manager),
    )

    first = agent.save_shutdown_summary()
    second = agent.save_shutdown_summary()

    assert "Valuable prior synthesis." in second
    assert second.count("## Durable state at last shutdown") == 1
    assert len(second) == len(first)


def test_shutdown_summary_without_prior_synthesis_does_not_duplicate_durable_state(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    agent = MalDroidAgent(
        app_config,
        case,
        FakeClient(),
        registry,
        dispatcher,
        SessionManager(case, manager),
    )

    first = agent.save_shutdown_summary()
    second = agent.save_shutdown_summary()

    assert first == second
    assert second.count("Active profile:") == 1
    assert second.count("## Durable state at last shutdown") == 1


def test_latest_summary_uses_numeric_session_order(app_config: AppConfig) -> None:
    manager, case, _, _ = make_dispatcher(app_config)
    directory = case.internal / "sessions"
    (directory / "session-9999-summary.md").write_text(
        "# Session Summary\n\nolder\n", encoding="utf-8"
    )
    (directory / "session-10000-summary.md").write_text(
        "# Session Summary\n\nnewer\n", encoding="utf-8"
    )

    assert SessionManager.load_latest_summary(case) == "newer"


class CheckpointingClient:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    def complete(self, messages, tools):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="inspect-1",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )
        if self.calls == 2:
            return AssistantMessage(content="The sample is a small text artifact.")
        raise AssertionError("The final answer must not trigger another model generation")


def test_agent_saves_checkpoint_without_delaying_final_answer(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    sessions = SessionManager(case, manager)
    client = CheckpointingClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)

    response = agent.respond("Inspect the sample")

    assert response == "The sample is a small text artifact."
    assert client.calls == 2
    assert case.state.checkpoints[-1].automatic is True
    assert "small text artifact" in case.state.checkpoints[-1].completed_work[0]
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    assert "automatic_checkpoint" in {event["type"] for event in events}


class CheckpointIgnoringClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="inspect-1",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )
        return AssistantMessage(content="Metadata inspected; read the suspicious range next.")


def test_agent_saves_automatic_checkpoint_when_model_ignores_reminder(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(
        app_config,
        case,
        CheckpointIgnoringClient(),
        registry,
        dispatcher,
        sessions,
    )

    response = agent.respond("Inspect the sample")

    assert response == "Metadata inspected; read the suspicious range next."
    checkpoint = case.state.checkpoints[-1]
    assert checkpoint.automatic is True
    assert "read the suspicious range next" in checkpoint.completed_work[0]
    rendered = checkpoint.model_dump_json()
    assert "MalDroid_get_file_info" not in rendered
    assert '"path":"sample.txt"' not in rendered
    assert case.state.notes == []


def test_agent_recovers_reasoning_only_empty_response_without_polluting_history(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)

    class EmptyThenHealthyClient:
        reasoning_level = "medium"

        def __init__(self) -> None:
            self.calls = 0
            self.levels = []

        def set_reasoning_level(self, level) -> None:
            self.reasoning_level = level
            self.levels.append(level)

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AssistantMessage(
                    content=None,
                    reasoning_content="budget exhausted before an answer",
                    finish_reason="length",
                )
            assert any("without visible content" in item.get("content", "") for item in messages)
            return AssistantMessage(content="Recovered answer.", finish_reason="stop")

    client = EmptyThenHealthyClient()
    events = []
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, data: events.append((event, data)),
    )

    assert agent.respond("Answer this") == "Recovered answer."
    assert client.calls == 2
    assert client.levels == ["off", "medium"]
    assert not any(
        message.get("role") == "assistant" and not message.get("content")
        for message in agent.messages
    )
    assert {event for event, _ in events} >= {
        "empty_response_recovery",
        "empty_response_recovered",
    }


def test_agent_strips_completed_turn_reasoning_before_next_user_turn(
    app_config: AppConfig,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)

    class TwoTurnClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return AssistantMessage(content="First answer.", reasoning_content="old thought")
            assert not any(message.get("reasoning_content") for message in messages)
            return AssistantMessage(content="Second answer.")

    agent = MalDroidAgent(
        app_config,
        case,
        TwoTurnClient(),
        registry,
        dispatcher,
        sessions,
    )

    assert agent.respond("First") == "First answer."
    assert agent.respond("Second") == "Second answer."
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    assert "reasoning_history_pruned" in {event["type"] for event in events}


class StructuredStateClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="inspect",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )
        if self.calls == 2:
            assert any(message.get("content") == STATE_DISCIPLINE_REMINDER for message in messages)
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="todo-add",
                        name=mcp_tool_name("update_todo"),
                        arguments='{"action":"add","text_or_id":"Inspect sample metadata"}',
                    )
                ],
            )
        if self.calls == 3:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="finding",
                        name=mcp_tool_name("save_finding"),
                        arguments=(
                            '{"title":"Text artifact identified","summary":"sample.txt is a '
                            'regular text artifact.","confidence":"high","severity":'
                            '"informational","status":"confirmed","evidence":[{"path":'
                            '"sample.txt","description":"Metadata inspection",'
                            '"tool":"MalDroid_get_file_info"}],"tags":["fixture"]}'
                        ),
                    )
                ],
            )
        if self.calls == 4:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="todo-complete",
                        name=mcp_tool_name("update_todo"),
                        arguments='{"action":"complete","text_or_id":"TODO-0001"}',
                    )
                ],
            )
        if self.calls == 5:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="note",
                        name=mcp_tool_name("save_note"),
                        arguments=(
                            '{"text":"Confirmed the artifact type and completed metadata review. '
                            'No unresolved work remains."}'
                        ),
                    ),
                ],
            )
        return AssistantMessage(content="Investigation state and evidence are saved.")


def test_agent_drives_todos_findings_and_meaningful_notes(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    agent = MalDroidAgent(
        app_config,
        case,
        StructuredStateClient(),
        registry,
        dispatcher,
        SessionManager(case, manager),
    )

    response = agent.respond("Inspect the sample fully")

    assert response == "Investigation state and evidence are saved."
    assert case.state.todos[0].status == "completed"
    assert case.state.findings[0].title == "Text artifact identified"
    assert case.state.findings[0].evidence[0].path == "sample.txt"
    assert case.state.notes[-1].text.startswith("Confirmed the artifact type")


class FailingCompactionClient:
    @staticmethod
    def complete(messages, tools):
        raise RuntimeError("context exhausted")


def test_compaction_falls_back_to_durable_case_state(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    dispatcher.execute(mcp_tool_name("save_note"), {"text": "Resume at sample.txt line 42."})
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(
        app_config,
        case,
        FailingCompactionClient(),
        registry,
        dispatcher,
        sessions,
    )

    summary = agent.compact()

    assert "Model compaction failed" in summary
    assert "Resume at sample.txt line 42" in summary
    assert case.state.summary == summary


def test_auto_compaction_threshold_is_configurable(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(app_config, case, FakeClient(), registry, dispatcher, sessions)
    agent.messages.append({"role": "user", "content": "x" * 190000})
    assert agent.should_auto_compact() is True


def test_old_tool_payloads_are_pruned_from_active_context_only(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["limits"]["retained_tool_results"] = 2
    config = AppConfig.model_validate(data)
    manager, case, registry, dispatcher = make_dispatcher(config)
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(config, case, FakeClient(), registry, dispatcher, sessions)
    for number in range(4):
        agent.messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call-{number}",
                "content": json.dumps({"status": "completed", "data": "evidence-" + "x" * 5000}),
            }
        )

    before = agent.estimate_tokens()
    agent._prune_working_context()
    after = agent.estimate_tokens()

    assert after < before - 2000
    assert "context_compacted" in agent.messages[-4]["content"]
    assert "evidence-" in agent.messages[-1]["content"]
    history = sessions.history_path.read_text(encoding="utf-8")
    assert "context_prune" in history


class ReasoningClient(FakeClient):
    reasoning_level = "unlimited"

    def set_reasoning_level(self, level) -> None:
        self.reasoning_level = level


def test_agent_changes_reasoning_level_and_records_session(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    agent = MalDroidAgent(
        app_config,
        case,
        ReasoningClient(),
        registry,
        dispatcher,
        sessions,
    )

    agent.set_reasoning_level("high")

    assert agent.reasoning_level == "high"
    events = [json.loads(line) for line in sessions.history_path.read_text().splitlines()]
    change = next(event for event in events if event["type"] == "reasoning_change")
    assert change["content"] == {"level": "high", "thinking_budget_tokens": 1536}


class LongTaskClient:
    def __init__(self) -> None:
        self.tool_turns = 0
        self.compactions = 0

    def complete(self, messages, tools):
        if not tools:
            self.compactions += 1
            return AssistantMessage(content="Phase summary with exact next action.")
        if self.tool_turns < 3:
            self.tool_turns += 1
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=f"long-{self.tool_turns}",
                        name=mcp_tool_name("get_file_info"),
                        arguments='{"path":"sample.txt"}',
                    )
                ],
            )
        return AssistantMessage(content="The long investigation is complete.")


def test_agent_rolls_long_task_into_next_phase_without_stopping(
    app_config: AppConfig,
) -> None:
    data = app_config.model_dump()
    data["limits"]["max_tool_rounds"] = 2
    data["limits"]["max_task_phases"] = 0
    config = AppConfig.model_validate(data)
    manager, case, registry, dispatcher = make_dispatcher(config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    sessions = SessionManager(case, manager)
    client = LongTaskClient()
    reported = []
    agent = MalDroidAgent(
        config,
        case,
        client,
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, details: reported.append((event, details)),
    )

    response = agent.respond("Complete a multi-phase investigation")

    assert response == "The long investigation is complete."
    assert client.tool_turns == 3
    assert client.compactions == 0
    assert any(event == "phase_rollover" for event, _ in reported)
    checkpoint = next(item for item in case.state.checkpoints if item.phase == 1)
    assert checkpoint.automatic is True
    assert "MalDroid_get_file_info" not in checkpoint.model_dump_json()
    assert case.state.notes == []
    assert any(event == "state_discipline_required" for event, _ in reported)


def test_agent_compacts_inside_active_task_when_context_threshold_is_reached(
    app_config: AppConfig,
) -> None:
    data = app_config.model_dump()
    data["limits"]["max_tool_rounds"] = 8
    data["limits"]["max_task_phases"] = 0
    config = AppConfig.model_validate(data)
    manager, case, registry, dispatcher = make_dispatcher(config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    sessions = SessionManager(case, manager)
    client = LongTaskClient()
    reported = []
    agent = MalDroidAgent(
        config,
        case,
        client,
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, details: reported.append((event, details)),
    )

    response = agent.respond("Investigate fully. " + "context " * 24000)

    assert response == "The long investigation is complete."
    rollover = next(details for event, details in reported if event == "phase_rollover")
    assert rollover["reason"] == "context_threshold"
    assert client.compactions >= 1


def test_legacy_saved_phase_ceiling_no_longer_stops_agent(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["limits"]["max_tool_rounds"] = 1
    data["limits"]["max_task_phases"] = 2
    config = AppConfig.model_validate(data)
    manager, case, registry, dispatcher = make_dispatcher(config)
    (case.root / "sample.txt").write_text("evidence\n", encoding="utf-8")
    client = LongTaskClient()
    agent = MalDroidAgent(
        config,
        case,
        client,
        registry,
        dispatcher,
        SessionManager(case, manager),
    )

    response = agent.respond("Continue beyond the legacy phase limit")

    assert response == "The long investigation is complete."
    assert client.tool_turns == 3
    assert client.compactions == 0


class FlakyClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("temporary local server disconnect")
        return AssistantMessage(content="Recovered and completed.")


def test_agent_retries_transient_model_failure(
    app_config: AppConfig,
    monkeypatch,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    client = FlakyClient()
    delays = []
    reported = []
    monkeypatch.setattr("maldroid.agent.time.sleep", delays.append)
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        registry,
        dispatcher,
        sessions,
        event_handler=lambda event, details: reported.append((event, details)),
    )

    response = agent.respond("Finish despite a transient disconnect")

    assert response == "Recovered and completed."
    assert client.calls == 2
    assert delays == [1.0]
    assert any(event == "model_retry" for event, _ in reported)


def test_agent_does_not_retry_non_transient_model_request_error(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    sessions = SessionManager(case, manager)
    delays = []
    monkeypatch.setattr("maldroid.agent.time.sleep", delays.append)

    class BadRequestError(RuntimeError):
        status_code = 400

    class BadRequestClient:
        calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            raise BadRequestError("invalid chat template request")

    client = BadRequestClient()
    agent = MalDroidAgent(app_config, case, client, registry, dispatcher, sessions)

    with pytest.raises(RuntimeError, match="invalid chat template"):
        agent.respond("Try once")
    assert client.calls == 1
    assert delays == []


class RepeatingThenHealthyClient:
    def __init__(self, failures: int = 1) -> None:
        self.calls = 0
        self.failures = failures
        self.messages = []

    def complete(self, messages, tools):
        self.calls += 1
        self.messages = messages
        if self.calls <= self.failures:
            raise RepetitiveGenerationError(RepetitionMatch(5, 12, 60), "answer")
        return AssistantMessage(content="Recovered without repetition.")


def test_agent_recovers_repetition_in_fresh_session(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    original = SessionManager(case, manager)
    client = RepeatingThenHealthyClient()
    reported = []
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        registry,
        dispatcher,
        original,
        event_handler=lambda event, details: reported.append((event, details)),
    )
    agent.messages.append({"role": "tool", "content": '{"data":"RECENT-EVIDENCE"}'})

    response = agent.respond("בדוק את הקובץ")

    assert response == "Recovered without repetition."
    assert client.calls == 2
    assert agent.sessions.number == original.number + 1
    assert any(event == "repetition_recovery" for event, _ in reported)
    assert any(message.get("content") == "בדוק את הקובץ" for message in client.messages)
    assert "mechanical repetition loop" in "\n".join(
        str(message.get("content", "")) for message in client.messages
    )
    assert "RECENT-EVIDENCE" in str(client.messages)
    assert "RECENT-EVIDENCE" not in original.summary_path.read_text(encoding="utf-8")
    assert "שלום" not in original.history_path.read_text(encoding="utf-8")
    recovered_events = [
        json.loads(line)
        for line in agent.sessions.history_path.read_text(encoding="utf-8").splitlines()
    ]
    recovered_user = [
        event
        for event in recovered_events
        if event.get("type") == "message" and event.get("role") == "user"
    ]
    assert recovered_user[-1]["content"] == "בדוק את הקובץ"
    assert recovered_user[-1]["recovered_from_session"] == original.number


def test_agent_bounds_repetition_recovery_attempts(app_config: AppConfig) -> None:
    manager, case, registry, dispatcher = make_dispatcher(app_config)
    client = RepeatingThenHealthyClient(failures=10)
    agent = MalDroidAgent(
        app_config,
        case,
        client,
        registry,
        dispatcher,
        SessionManager(case, manager),
    )

    response = agent.respond("Inspect safely")

    assert "Generation was stopped" in response
    assert client.calls == 3
    assert agent.sessions.number == 3
