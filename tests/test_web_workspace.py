from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from maldroid.config import AppConfig
from maldroid.exceptions import MalDroidError
from maldroid.runtime_lock import RuntimeLease
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
    assert 'data-key="llama.repetition_recovery_enabled"' in page


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
        ]
    )
    serialized = str(timeline)
    assert "Visible answer" in serialized
    assert "MalDroid_search_text" in serialized
    assert "hidden chain" not in serialized
    assert "arguments" not in serialized
