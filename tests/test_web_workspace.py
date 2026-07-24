from __future__ import annotations

import asyncio
import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from maldroid import runtime_lock
from maldroid.config import AppConfig
from maldroid.exceptions import MalDroidError, TurnCancelledError
from maldroid.runtime_lock import RuntimeLease
from maldroid.session_manager import SessionManager
from maldroid.web.server import WebWorkspace, create_app


def web_config(tmp_path: Path) -> AppConfig:
    data = AppConfig().model_dump()
    data["general"]["cases_directory"] = str(tmp_path / "cases")
    data["llama"]["model"] = str(tmp_path / "model.gguf")
    return AppConfig.model_validate(data)


def authorized_client(workspace: WebWorkspace, token: str = "test-token") -> TestClient:
    client = TestClient(create_app(workspace, token), base_url="http://localhost")
    response = client.get(f"/?token={token}", follow_redirects=False)
    assert response.status_code == 303
    return client


def test_web_api_requires_per_process_token(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    with TestClient(create_app(workspace, "secret"), base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200
        response = client.get("/api/bootstrap")
        assert response.status_code == 401
        assert response.json()["error"] == "Unauthorized local workspace request"


def test_web_settings_expose_enabled_repetition_recovery(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    with authorized_client(workspace) as client:
        bootstrap = client.get("/api/bootstrap").json()
        page = client.get("/").text

    assert bootstrap["settings"]["llama"]["repetition_recovery_enabled"] is True
    assert bootstrap["settings"]["llama"]["stream_idle_timeout_seconds"] == 120
    assert 'data-key="llama.repetition_recovery_enabled"' in page
    assert 'data-key="llama.stream_idle_timeout_seconds"' in page


def test_web_shell_exposes_chat_theme_sidebar_restore_and_file_controls(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    with authorized_client(workspace) as client:
        page = client.get("/").text
        styles = client.get("/assets/styles.css").text
        script = client.get("/assets/app.js").text

    assert 'id="message-input"' in page
    assert "Message MalDroid" in page
    assert 'id="theme-toggle"' in page
    assert 'id="theme-setting"' in page
    assert 'id="stop-workspace"' in page
    assert 'id="file-filter"' in page
    assert 'id="toggle-logs"' in page
    assert "Used in latest turn" in page
    assert ".composer-disabled.hidden+.composer{display:block}" in styles
    assert "body.sidebar-collapsed .mobile-menu{display:grid}" in styles
    assert "--side-pane:clamp(224px,19vw,276px)" in styles
    assert "--sidebar:var(--side-pane);--inspector:var(--side-pane)" in styles
    assert "--workspace-shift" in styles
    assert "--balanced-content-width" in styles
    assert "minmax(0,1fr)" in styles
    assert "@media(max-width:900px)" in styles
    assert ".inspector.open{transform:none}" in styles
    assert 'localStorage.setItem("maldroid-theme"' in script
    assert 'api("/api/workspace/stop"' in script
    assert "collapsedDirectories" in script
    assert "touchedFiles" in script
    assert "markTouchedFiles" in script
    assert "isLogPath" in script
    assert 'localStorage.setItem("maldroid-show-logs"' in script
    assert "syncPaneState" in script


def test_web_shell_exposes_live_operational_progress_without_private_reasoning(
    tmp_path: Path,
) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    with authorized_client(workspace) as client:
        page = client.get("/").text
        styles = client.get("/assets/styles.css").text
        script = client.get("/assets/app.js").text

    assert 'id="turn-progress"' in page
    assert 'id="work-elapsed"' in page
    assert 'id="live-work-steps"' in page
    assert 'id="stop-turn"' in page
    assert 'data-action="stop-turn"' in page
    assert "private model reasoning is never exposed" in page
    assert ".live-work-metrics" in styles
    assert "startLiveWork" in script
    assert "appendLiveWorkStep" in script
    assert "liveToolDetail" in script
    assert "input_tokens_estimate" in script
    assert "completion_tokens_estimate" in script
    assert 'type:"stop"' in script
    assert 'message.type === "turn_stopped"' in script
    assert "prompt_progress" in script
    assert "generation_first_token" in script
    assert "empty_response_recovery" in script
    assert "Local model offline. Check Settings" in script


def test_web_socket_reconnect_resynchronizes_workspace_and_busy_state(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    with authorized_client(workspace) as client:
        script = client.get("/assets/app.js").text

    assert 'message.type === "connected"' in script
    assert "state.workspace = message.workspace" in script
    assert "state.workspace.case?.case_id || null" in script
    assert "else clearProjectData()" in script
    assert "setBusy(false)" in script
    assert "socketQueue: Promise.resolve()" in script
    assert "state.socketQueue = state.socketQueue" in script


def test_web_returns_answer_before_post_turn_compaction(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))

    class FakeAgent:
        compact_calls = 0
        compact_checks = 0

        def should_auto_compact(self) -> bool:
            self.compact_checks += 1
            return False

        @staticmethod
        def respond(text: str) -> str:
            assert text == "Investigate"
            return "Ready now."

        def compact(self) -> None:
            self.compact_calls += 1

        @staticmethod
        def finish_turn() -> None:
            pass

    agent = FakeAgent()
    workspace.runtime = SimpleNamespace(agent=agent)

    assert workspace.respond("Investigate") == "Ready now."
    assert agent.compact_checks == 1
    assert agent.compact_calls == 0


def test_web_project_creation_listing_and_bounded_file_preview(tmp_path: Path) -> None:
    source = tmp_path / "decompiled-app"
    source.mkdir()
    (source / "index.js").write_text("const greeting = 'שלום';\n", encoding="utf-8")
    workspace = WebWorkspace(web_config(tmp_path))
    with authorized_client(workspace) as client:
        created = client.post(
            "/api/projects",
            json={"name": "RTL research", "source_path": str(source), "profile": "react-native"},
        )
        assert created.status_code == 201
        case_id = created.json()["project"]["case_id"]

        bootstrap = client.get("/api/bootstrap").json()
        assert bootstrap["projects"][0]["name"] == "RTL research"
        assert bootstrap["projects"][0]["profile"] == "react-native"

        files = client.get(f"/api/projects/{case_id}/files?depth=3").json()
        assert any(item["path"] == "index.js" for item in files["data"]["entries"])
        preview = client.get(
            f"/api/projects/{case_id}/file", params={"path": "index.js", "start": 1, "end": 5}
        ).json()
        assert preview["status"] == "completed"
        assert preview["data"]["lines"][0]["text"] == "const greeting = 'שלום';"


def test_invalid_web_profile_does_not_leave_a_ghost_project(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    before = {item["case_id"] for item in workspace.projects()}

    with pytest.raises(MalDroidError, match="Unknown profile"):
        workspace.create_project({"name": "must roll back", "profile": "not-a-profile"})

    assert {item["case_id"] for item in workspace.projects()} == before


def test_web_commands_and_project_switches_reject_an_active_model_turn(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    case = workspace.manager.create("busy")
    workspace.runtime = SimpleNamespace(
        case=case,
        agent=SimpleNamespace(sessions=SessionManager(case, workspace.manager)),
        dispatcher=SimpleNamespace(),
    )
    assert workspace._turn_lock.acquire(blocking=False)
    try:
        with pytest.raises(MalDroidError, match="model turn is already running"):
            workspace.command("status", {})
        with pytest.raises(MalDroidError, match="model turn is already running"):
            workspace.activate(case.metadata.case_id)
    finally:
        workspace._turn_lock.release()


def test_web_event_emission_tolerates_a_closed_reconnect_loop(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    workspace.bind_events(loop, queue)  # type: ignore[arg-type]
    loop.close()

    workspace.emit("tool_start", {"name": "MalDroid_read_file_range"})


def test_web_history_streams_and_bounds_long_session_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    case = workspace.manager.create("long-session")
    sessions = SessionManager(case, workspace.manager)
    for number in range(510):
        sessions.record("message", role="user", content=f"message-{number}")
    original_read_text = Path.read_text

    def reject_jsonl_read_text(path: Path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise AssertionError("session JSONL must be streamed, not loaded in full")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_jsonl_read_text)

    messages = workspace.history(case.metadata.case_id)
    events = workspace.session_events(case, limit=25)

    assert len(messages) == 500
    assert messages[0]["content"] == "message-10"
    assert messages[-1]["content"] == "message-509"
    assert len(events) == 25


def test_web_history_command_reports_the_agent_current_session(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    case = workspace.manager.create("recovered-session")
    stale = SessionManager(case, workspace.manager)
    current = SessionManager(case, workspace.manager)
    agent = SimpleNamespace(sessions=current)
    workspace.runtime = SimpleNamespace(
        case=case,
        agent=agent,
        dispatcher=SimpleNamespace(),
        sessions=stale,
    )

    result = workspace.command("history", {})

    assert result["data"]["session"] == current.history_path.name


def test_websocket_returns_workspace_snapshot(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    with (
        authorized_client(workspace) as client,
        client.websocket_connect(
            "/ws",
            headers={"cookie": "maldroid_web_token=test-token", "host": "localhost"},
        ) as socket,
    ):
        connected = socket.receive_json()
        assert connected == {"type": "connected", "workspace": {"active": False}}


def test_websocket_stop_interrupts_an_active_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    started = threading.Event()
    cancelled = threading.Event()

    def blocking_respond(text: str) -> str:
        assert text == "Investigate this"
        started.set()
        cancelled.wait(2)
        raise TurnCancelledError("Turn stopped by user.")

    monkeypatch.setattr(workspace, "respond", blocking_respond)
    monkeypatch.setattr(workspace, "cancel_turn", cancelled.set)
    with (
        authorized_client(workspace) as client,
        client.websocket_connect(
            "/ws",
            headers={"cookie": "maldroid_web_token=test-token", "host": "localhost"},
        ) as socket,
    ):
        socket.receive_json()
        socket.send_json({"type": "message", "content": "Investigate this"})
        assert socket.receive_json()["type"] == "turn_start"
        assert started.wait(1)
        socket.send_json({"type": "stop"})
        assert socket.receive_json()["type"] == "turn_stopping"
        stopped = socket.receive_json()

    assert stopped["type"] == "turn_stopped"
    assert stopped["workspace"] == {"active": False}


def test_runtime_lease_rejects_parallel_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("maldroid.runtime_lock.data_directory", lambda: tmp_path)
    first = RuntimeLease("Web").acquire()
    try:
        with pytest.raises(MalDroidError, match="already running"):
            RuntimeLease("CLI").acquire()
    finally:
        first.release()


def test_runtime_lease_releases_lock_when_metadata_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("maldroid.runtime_lock.data_directory", lambda: tmp_path)
    real_write = runtime_lock.atomic_write_json

    def fail_write(*_args, **_kwargs) -> None:
        raise OSError("metadata is read-only")

    monkeypatch.setattr("maldroid.runtime_lock.atomic_write_json", fail_write)
    with pytest.raises(OSError, match="read-only"):
        RuntimeLease("Web").acquire()

    monkeypatch.setattr("maldroid.runtime_lock.atomic_write_json", real_write)
    second = RuntimeLease("CLI").acquire()
    second.release()


def test_web_config_is_loopback_only() -> None:
    data = AppConfig().model_dump()
    data["web"]["host"] = "0.0.0.0"
    with pytest.raises(ValueError):
        AppConfig.model_validate(data)


def test_production_websocket_backend_is_an_explicit_runtime_dependency() -> None:
    assert importlib.util.find_spec("websockets") is not None


def test_web_timeline_never_exposes_hidden_reasoning(tmp_path: Path) -> None:
    workspace = WebWorkspace(web_config(tmp_path))
    timeline = workspace._safe_timeline(
        [
            {
                "timestamp": "2026-07-15T12:00:00+03:00",
                "type": "message",
                "role": "assistant",
                "content": {"content": "Visible answer", "reasoning_content": "hidden chain"},
            },
            {
                "timestamp": "2026-07-15T12:01:00+03:00",
                "type": "tool_call",
                "content": {"name": "MalDroid_search_text", "arguments": {"query": "x"}},
            },
            {
                "timestamp": "2026-07-15T12:02:00+03:00",
                "type": "turn_cancelled",
                "content": {"objective": "private stopped request"},
            },
            {
                "timestamp": "2026-07-15T12:03:00+03:00",
                "type": "code_snippet_captured",
                "content": {
                    "path": "workspace/snippets/SNIPPET-0001.js",
                    "sha256": "private-source-fingerprint",
                },
            },
        ]
    )
    serialized = str(timeline)
    assert "Visible answer" in serialized
    assert "MalDroid_search_text" in serialized
    assert "hidden chain" not in serialized
    assert "arguments" not in serialized
    assert "turn_cancelled" in serialized
    assert "private stopped request" not in serialized
    assert "workspace/snippets/SNIPPET-0001.js" in serialized
    assert "private-source-fingerprint" not in serialized
