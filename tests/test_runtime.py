from __future__ import annotations

from types import SimpleNamespace

from maldroid.case_manager import CaseManager
from maldroid.runtime import WorkspaceRuntime
from maldroid.session_manager import SessionManager


def test_runtime_stop_uses_deterministic_summary_without_model_generation(app_config) -> None:
    manager = CaseManager(app_config)
    case = manager.create("runtime-stop")
    current_sessions = SessionManager(case, manager)
    calls: list[str] = []

    class FakeAgent:
        sessions = current_sessions

        @staticmethod
        def compact() -> None:
            raise AssertionError("runtime shutdown must never start a model generation")

        @staticmethod
        def save_shutdown_summary() -> str:
            calls.append("summary")
            return "durable shutdown summary"

    runtime = WorkspaceRuntime(app_config, case, manager)
    runtime.agent = FakeAgent()  # type: ignore[assignment]
    runtime.sessions = SessionManager(case, manager)
    runtime.server = SimpleNamespace(stop=lambda: calls.append("server"))

    runtime.stop()

    assert calls == ["summary", "server"]
    assert runtime.agent is None


def test_runtime_stop_continues_cleanup_when_summary_and_mcp_stop_fail(app_config) -> None:
    manager = CaseManager(app_config)
    case = manager.create("runtime-stop-failures")
    calls: list[str] = []

    class BrokenSessions:
        @staticmethod
        def record(*_args, **_kwargs) -> None:
            calls.append("record")
            raise OSError("read-only session log")

    class FakeAgent:
        sessions = BrokenSessions()

        @staticmethod
        def save_shutdown_summary() -> str:
            calls.append("summary")
            raise OSError("read-only summary")

    class BrokenMcp:
        @staticmethod
        def stop() -> None:
            calls.append("mcp")
            raise RuntimeError("MCP stop failed")

    runtime = WorkspaceRuntime(app_config, case, manager)
    runtime.agent = FakeAgent()  # type: ignore[assignment]
    runtime.sessions = SessionManager(case, manager)
    runtime.mcp_server = BrokenMcp()  # type: ignore[assignment]
    runtime.server = SimpleNamespace(stop=lambda: calls.append("server"))

    runtime.stop()

    assert calls == ["summary", "record", "mcp", "server"]
    assert runtime.agent is None
