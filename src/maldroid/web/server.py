"""Authenticated loopback-only Web workspace with the same MalDroid runtime as the CLI."""

from __future__ import annotations

import asyncio
import json
import secrets
import socket
import threading
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import uvicorn
from starlette.applications import Starlette
from starlette.datastructures import URL
from starlette.endpoints import WebSocketEndpoint
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from maldroid.case_manager import Case, CaseManager
from maldroid.config import (
    AppConfig,
    default_config_path,
    load_config,
    save_config,
    set_config_value,
)
from maldroid.constants import VERSION
from maldroid.evidence_manager import EvidenceManager
from maldroid.exceptions import MalDroidError, TurnCancelledError
from maldroid.external_mcp import ExternalMcpClient, ExternalMcpRegistryManager
from maldroid.paths import expand_path
from maldroid.profiles import PROFILES, get_profile
from maldroid.runtime import WorkspaceRuntime, build_tool_runtime
from maldroid.runtime_lock import RuntimeLease
from maldroid.tools.models import mcp_tool_name

STATIC = Path(__file__).with_name("static")
COOKIE = "maldroid_web_token"


class TokenAuthMiddleware:
    """Block local cross-site requests; a random per-process token is required."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path in {"/", "/health"} or path.startswith("/assets/"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        cookies = headers.get(b"cookie", b"").decode("latin-1")
        authorized = any(part.strip() == f"{COOKIE}={self.token}" for part in cookies.split(";"))
        if authorized:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
        else:
            response = JSONResponse(
                {"error": "Unauthorized local workspace request"}, status_code=401
            )
            await response(scope, receive, send)


class WebWorkspace:
    """Single-model workspace controller; only one case can consume model memory at once."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.manager = CaseManager(config)
        self.runtime: WorkspaceRuntime | None = None
        self.selected_case: Case | None = None
        self._runtime_lock = threading.RLock()
        self._turn_lock = threading.Lock()
        self._turn_cancel_requested = threading.Event()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._event_queue: asyncio.Queue[dict[str, Any]] | None = None

    def projects(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.manager.list_cases()]

    def resolve_case(self, case_id: str, *, touch: bool = False) -> Case:
        record = next((item for item in self.projects() if item["case_id"] == case_id), None)
        if record is None:
            raise MalDroidError(f"Unknown project: {case_id}")
        return (
            self.manager.open(Path(str(record["path"])))
            if touch
            else self.manager._load_without_touch(Path(str(record["path"])))
        )

    def create_project(self, payload: dict[str, Any]) -> Case:
        name = str(payload.get("name") or "New investigation").strip()[:128]
        source = str(payload.get("source_path") or "").strip()
        if not source:
            case = self.manager.create(name)
        else:
            target = expand_path(Path(source))
            if target.is_dir():
                case = (
                    self.manager.open(target)
                    if (target / ".maldroid" / "case.toml").exists()
                    else self.manager.initialize_existing(target, name)
                )
            elif target.is_file():
                case = self.manager.create(name)
                mode = payload.get("evidence_mode")
                EvidenceManager(self.manager).register(
                    case, target, "copy" if mode == "copy" else "symlink"
                )
            else:
                raise MalDroidError(f"Source path does not exist: {target}")
        profile = str(payload.get("profile") or self.config.general.default_profile)
        definition = get_profile(profile)
        if definition.status != "implemented":
            raise MalDroidError(f"Profile is not implemented: {profile}")
        case.state.active_profile = profile
        self.manager.save(case)
        return case

    def activate(self, case_id: str) -> dict[str, Any]:
        with self._runtime_lock:
            case = self.resolve_case(case_id, touch=True)
            if self.runtime is not None:
                if self.runtime.case.metadata.case_id == case_id:
                    return self.snapshot()
                self.runtime.stop()
            self.selected_case = case
            self.runtime = WorkspaceRuntime(
                self.config,
                case,
                self.manager,
                event_handler=self.emit,
            )
            try:
                self.runtime.start()
            except Exception:
                self.runtime.stop(compact=False)
                self.runtime = None
                raise
            return self.snapshot()

    def stop_runtime(self) -> None:
        with self._runtime_lock:
            if self.runtime is not None:
                self.runtime.stop()
                self.runtime = None

    def bind_events(
        self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        self._event_loop = loop
        self._event_queue = queue

    def unbind_events(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if self._event_queue is queue:
            self._event_queue = None
            self._event_loop = None

    def emit(self, event: str, data: dict[str, Any]) -> None:
        loop, queue = self._event_loop, self._event_queue
        if loop is not None and queue is not None:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "activity", "event": event, "data": data}
            )

    def respond(self, text: str) -> str:
        if not self._turn_lock.acquire(blocking=False):
            raise MalDroidError("Another model turn is already running.")
        try:
            if self._turn_cancel_requested.is_set():
                raise TurnCancelledError("Turn stopped by user.")
            runtime = self._require_runtime()
            assert runtime.agent is not None
            if runtime.agent.should_auto_compact():
                runtime.agent.compact()
            response = runtime.agent.respond(text)
            if runtime.agent.should_auto_compact():
                runtime.agent.compact()
            return response
        finally:
            self._turn_cancel_requested.clear()
            current_runtime = self.runtime
            if current_runtime is not None and current_runtime.agent is not None:
                current_runtime.agent.finish_turn()
            self._turn_lock.release()

    def prepare_turn(self) -> None:
        """Reset the Web cancellation signal before scheduling a new turn."""
        if self._turn_lock.locked():
            raise MalDroidError("Another model turn is already running.")
        self._turn_cancel_requested.clear()

    def cancel_turn(self) -> None:
        """Request cancellation without stopping the shared model runtime."""
        self._turn_cancel_requested.set()
        runtime = self.runtime
        if runtime is not None and runtime.agent is not None:
            runtime.agent.cancel_turn()

    def command(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        runtime = self._require_runtime()
        assert runtime.agent is not None
        assert runtime.dispatcher is not None
        agent = runtime.agent
        tool_actions = {
            "dashboard": ("read_case_state", {}),
            "files": (
                "list_case_files",
                {"path": payload.get("path", "."), "max_depth": payload.get("max_depth", 4)},
            ),
            "inventory": ("inventory_case", {"path": payload.get("path", ".")}),
            "indicators": ("extract_network_indicators", {"path": payload.get("path", ".")}),
            "triage": ("search_behavior_patterns", {"path": payload.get("path", ".")}),
            "report": ("build_research_report", {}),
            "knowledge": (
                "search_knowledge",
                {"query": payload.get("query", "Android static analysis")},
            ),
            "note": (
                "save_note",
                {
                    "text": payload.get("text", ""),
                    "title": payload.get("title") or None,
                    "kind": payload.get("kind", "research_note"),
                    "evidence": payload.get("evidence", []),
                },
            ),
            "todo": (
                "update_todo",
                {
                    "action": payload.get("todo_action", "add"),
                    "text_or_id": payload.get("text_or_id", ""),
                },
            ),
        }
        if action in tool_actions:
            name, arguments = tool_actions[action]
            return runtime.dispatcher.execute(mcp_tool_name(name), arguments).model_dump(
                mode="json"
            )
        if action == "compact":
            return {"status": "completed", "data": {"summary": agent.compact()}}
        if action == "clear":
            agent.clear()
            return {"status": "completed", "data": {"preserved": "durable case state"}}
        if action == "status":
            return {"status": "completed", "data": self.snapshot()}
        if action == "tools":
            tools = agent.available_tool_schemas()
            return {
                "status": "completed",
                "data": {
                    "count": len(tools),
                    "tools": [item.get("function", {}) for item in tools],
                },
            }
        if action in {"findings", "checkpoints", "todos"}:
            key = "todos" if action == "todos" else action
            records = getattr(runtime.case.state, key)
            return {
                "status": "completed",
                "data": [item.model_dump(mode="json") for item in records],
            }
        if action in {"history", "timeline"}:
            events = self.session_events(runtime.case, limit=100 if action == "timeline" else 500)
            counts: dict[str, int] = {}
            for item in events:
                kind = str(item.get("type", "unknown"))
                counts[kind] = counts.get(kind, 0) + 1
            timeline = self._safe_timeline(events) if action == "timeline" else []
            return {
                "status": "completed",
                "data": {
                    "event_counts": counts,
                    "timeline": timeline,
                    "session": runtime.sessions.history_path.name if runtime.sessions else None,
                },
            }
        if action == "reasoning":
            agent.set_reasoning_level(str(payload["level"]))  # type: ignore[arg-type]
            return {"status": "completed", "data": {"level": agent.reasoning_level}}
        if action == "profile":
            profile = str(payload["profile"])
            if profile == "auto":
                agent.enable_auto_profile()
            else:
                definition = get_profile(profile)
                if definition.status != "implemented":
                    raise MalDroidError(f"Profile is not implemented: {profile}")
                agent.switch_profile(profile)
            return {
                "status": "completed",
                "data": {"profile": runtime.case.state.active_profile, "mode": agent.profile_mode},
            }
        raise MalDroidError(f"Unknown workspace action: {action}")

    def file_tree(self, case_id: str, path: str = ".", depth: int = 5) -> dict[str, Any]:
        case, dispatcher = self._case_dispatcher(case_id)
        result = dispatcher.execute(
            mcp_tool_name("list_case_files"), {"path": path, "max_depth": depth}
        )
        return _tool_data(result.model_dump(mode="json"), case)

    def file_content(self, case_id: str, path: str, start: int, end: int) -> dict[str, Any]:
        case, dispatcher = self._case_dispatcher(case_id)
        info = dispatcher.execute(mcp_tool_name("get_file_info"), {"path": path})
        if info.status != "completed":
            return info.model_dump(mode="json")
        if isinstance(info.data, dict) and info.data.get("binary"):
            result = dispatcher.execute(
                mcp_tool_name("read_byte_range"), {"path": path, "start_offset": 0, "length": 4096}
            )
        else:
            result = dispatcher.execute(
                mcp_tool_name("read_file_range"),
                {"path": path, "start_line": start, "end_line": end},
            )
        return _tool_data(result.model_dump(mode="json"), case)

    def history(self, case_id: str, session: str | None = None) -> list[dict[str, Any]]:
        case = self.resolve_case(case_id)
        directory = case.internal / "sessions"
        paths = sorted(directory.glob("session-*.jsonl"))
        if session:
            paths = [path for path in paths if path.name == Path(session).name]
        elif paths:
            paths = [paths[-1]]
        output: list[dict[str, Any]] = []
        for path in paths:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                with suppress(json.JSONDecodeError):
                    event = json.loads(line)
                    if event.get("type") == "message" and event.get("role") in {
                        "user",
                        "assistant",
                    }:
                        content = event.get("content")
                        if isinstance(content, dict):
                            content = content.get("content", "")
                        if content:
                            output.append(
                                {
                                    "role": event["role"],
                                    "content": content,
                                    "timestamp": event.get("timestamp"),
                                }
                            )
        return output

    def session_events(self, case: Case, limit: int = 100) -> list[dict[str, Any]]:
        directory = case.internal / "sessions"
        paths = sorted(directory.glob("session-*.jsonl"))
        if not paths:
            return []
        output: list[dict[str, Any]] = []
        for line in paths[-1].read_text(encoding="utf-8", errors="replace").splitlines():
            with suppress(json.JSONDecodeError):
                value = json.loads(line)
                if isinstance(value, dict):
                    output.append(value)
        return output[-limit:]

    @staticmethod
    def _safe_timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {
            "message",
            "tool_call",
            "tool_result",
            "profile_change",
            "compaction",
            "phase_checkpoint",
            "automatic_checkpoint",
            "turn_cancelled",
        }
        output: list[dict[str, Any]] = []
        for item in events:
            kind = str(item.get("type", ""))
            if kind not in allowed:
                continue
            content = item.get("content")
            detail = ""
            if kind == "message":
                if isinstance(content, dict):
                    detail = str(content.get("content") or "")[:300]
                elif item.get("role") == "user":
                    detail = str(content or "")[:300]
                else:
                    detail = "Assistant response recorded"
            elif isinstance(content, dict):
                detail = str(content.get("name") or content.get("status") or "")[:300]
            output.append(
                {
                    "timestamp": item.get("timestamp"),
                    "type": kind,
                    "role": item.get("role"),
                    "detail": detail,
                }
            )
        return output[-50:]

    def snapshot(self) -> dict[str, Any]:
        runtime = self.runtime
        case = runtime.case if runtime else self.selected_case
        if case is None:
            return {"active": False}
        agent = runtime.agent if runtime else None
        used = agent.estimate_tokens() if agent else 0
        return {
            "active": runtime is not None and agent is not None,
            "case": _case_payload(case),
            "context": {
                "used": used,
                "total": case.state.context_size,
                "ratio": used / max(1, case.state.context_size),
            },
            "profile_mode": agent.profile_mode if agent else "auto",
            "reasoning": agent.reasoning_level if agent else self.config.llama.reasoning_level,
            "mcp_endpoint": runtime.mcp_endpoint if runtime else None,
            "model_status": runtime.server.status() if runtime else {"running": False},
            "external_mcp": runtime.external_mcp.statuses
            if runtime and runtime.external_mcp
            else [],
        }

    def _case_dispatcher(self, case_id: str) -> tuple[Case, Any]:
        if self.runtime is not None and self.runtime.case.metadata.case_id == case_id:
            assert self.runtime.local_dispatcher is not None
            return self.runtime.case, self.runtime.local_dispatcher
        case = self.resolve_case(case_id)
        _, dispatcher = build_tool_runtime(self.config, case, self.manager)
        return case, dispatcher

    def _require_runtime(self) -> WorkspaceRuntime:
        if self.runtime is None or self.runtime.agent is None:
            raise MalDroidError("Open a project before using the model workspace.")
        return self.runtime


def create_app(workspace: WebWorkspace, token: str) -> Starlette:
    async def index(request: Request) -> Response:
        supplied = request.query_params.get("token")
        if supplied == token:
            clean = URL(str(request.url)).replace_query_params()
            response = RedirectResponse(str(clean), status_code=303)
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
            return response
        return FileResponse(STATIC / "index.html", headers=_security_headers())

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        if name not in {"app.js", "styles.css"}:
            return JSONResponse({"error": "Not found"}, status_code=404)
        media = "text/javascript" if name.endswith(".js") else "text/css"
        return FileResponse(STATIC / name, media_type=media, headers=_security_headers())

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "version": VERSION})

    async def bootstrap(_request: Request) -> Response:
        config = workspace.config
        return _json(
            {
                "version": VERSION,
                "projects": workspace.projects(),
                "workspace": workspace.snapshot(),
                "profiles": [vars(item) for item in PROFILES.values()],
                "settings": _safe_config(config),
                "config_path": str(default_config_path()),
                "connectors": [
                    item.model_dump(mode="json")
                    for item in ExternalMcpRegistryManager().load().servers
                ],
            }
        )

    async def create_project(request: Request) -> Response:
        case = workspace.create_project(await request.json())
        return _json({"project": _case_payload(case)}, 201)

    async def activate(request: Request) -> Response:
        return _json(await asyncio.to_thread(workspace.activate, request.path_params["case_id"]))

    async def stop(_request: Request) -> Response:
        await asyncio.to_thread(workspace.stop_runtime)
        return _json({"status": "stopped"})

    async def state(_request: Request) -> Response:
        return _json(workspace.snapshot())

    async def history(request: Request) -> Response:
        return _json(
            {
                "messages": workspace.history(
                    request.path_params["case_id"], request.query_params.get("session")
                )
            }
        )

    async def files(request: Request) -> Response:
        return _json(
            workspace.file_tree(
                request.path_params["case_id"],
                request.query_params.get("path", "."),
                int(request.query_params.get("depth", "5")),
            )
        )

    async def file_content(request: Request) -> Response:
        return _json(
            workspace.file_content(
                request.path_params["case_id"],
                request.query_params["path"],
                int(request.query_params.get("start", "1")),
                int(request.query_params.get("end", "500")),
            )
        )

    async def command(request: Request) -> Response:
        payload = await request.json()
        return _json(
            await asyncio.to_thread(workspace.command, str(payload.get("action")), payload)
        )

    async def update_settings(request: Request) -> Response:
        if workspace.runtime is not None:
            raise MalDroidError("Stop the active project before changing persistent settings.")
        payload = await request.json()
        config = load_config()
        for key, value in payload.items():
            config = set_config_value(config, str(key), str(value))
        save_config(config)
        workspace.config = config
        workspace.manager = CaseManager(config)
        return _json({"settings": _safe_config(config)})

    async def add_connector(request: Request) -> Response:
        payload = await request.json()
        server = ExternalMcpRegistryManager().add(str(payload["url"]), payload.get("nickname"))
        return _json({"connector": server.model_dump(mode="json")}, 201)

    async def delete_connector(request: Request) -> Response:
        server = ExternalMcpRegistryManager().remove(request.path_params["nickname"])
        return _json({"connector": server.model_dump(mode="json")})

    async def test_connector(request: Request) -> Response:
        server = ExternalMcpRegistryManager().get(request.path_params["nickname"])
        tools = await asyncio.to_thread(
            ExternalMcpClient(server, workspace.config.mcp.startup_timeout_seconds).list_tools
        )
        return _json(
            {
                "status": "connected",
                "tools": [{"name": item.name, "description": item.description} for item in tools],
            }
        )

    async def handled(request: Request, call: Any) -> Response:
        try:
            return await call(request)
        except (MalDroidError, ValueError, KeyError) as exc:
            return _json({"error": str(exc)}, 400)
        except Exception as exc:
            return _json({"error": str(exc)}, 500)

    def safe(call: Any) -> Any:
        async def endpoint(request: Request) -> Response:
            return await handled(request, call)

        return endpoint

    socket_class = type("WorkspaceSocket", (_WorkspaceSocket,), {"workspace": workspace})
    routes = [
        Route("/", index),
        Route("/health", health),
        Route("/assets/{name}", asset),
        Route("/api/bootstrap", safe(bootstrap)),
        Route("/api/projects", safe(create_project), methods=["POST"]),
        Route("/api/projects/{case_id}/activate", safe(activate), methods=["POST"]),
        Route("/api/projects/{case_id}/history", safe(history)),
        Route("/api/projects/{case_id}/files", safe(files)),
        Route("/api/projects/{case_id}/file", safe(file_content)),
        Route("/api/workspace", safe(state)),
        Route("/api/workspace/stop", safe(stop), methods=["POST"]),
        Route("/api/workspace/command", safe(command), methods=["POST"]),
        Route("/api/settings", safe(update_settings), methods=["PATCH"]),
        Route("/api/connectors", safe(add_connector), methods=["POST"]),
        Route("/api/connectors/{nickname}", safe(delete_connector), methods=["DELETE"]),
        Route("/api/connectors/{nickname}/test", safe(test_connector), methods=["POST"]),
        WebSocketRoute("/ws", socket_class),
    ]
    middleware = [
        Middleware(TokenAuthMiddleware, token=token),
        Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"]),
    ]
    return Starlette(routes=routes, middleware=middleware)


class _WorkspaceSocket(WebSocketEndpoint):
    encoding = "json"
    workspace: WebWorkspace

    async def on_connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        websocket.scope["event_queue"] = queue
        self.workspace.bind_events(asyncio.get_running_loop(), queue)
        websocket.scope["sender"] = asyncio.create_task(self._send_events(websocket, queue))
        await websocket.send_json({"type": "connected", "workspace": self.workspace.snapshot()})

    async def _send_events(
        self, websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        while True:
            await websocket.send_json(await queue.get())

    async def on_receive(self, websocket: WebSocket, data: Any) -> None:
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        try:
            if kind == "message":
                text = str(data.get("content") or "").strip()
                if not text:
                    raise MalDroidError("Message cannot be empty.")
                task = websocket.scope.get("turn_task")
                if isinstance(task, asyncio.Task) and not task.done():
                    raise MalDroidError("Another model turn is already running.")
                self.workspace.prepare_turn()
                await websocket.send_json({"type": "turn_start", "content": text})
                websocket.scope["turn_task"] = asyncio.create_task(self._run_turn(websocket, text))
            elif kind == "stop":
                task = websocket.scope.get("turn_task")
                if not isinstance(task, asyncio.Task) or task.done():
                    raise MalDroidError("No model turn is currently running.")
                await websocket.send_json({"type": "turn_stopping"})
                self.workspace.cancel_turn()
            elif kind == "activate":
                await websocket.send_json({"type": "runtime_start", "case_id": data.get("case_id")})
                result = await asyncio.to_thread(self.workspace.activate, str(data["case_id"]))
                await websocket.send_json({"type": "runtime_ready", "workspace": result})
            else:
                raise MalDroidError(f"Unknown socket action: {kind}")
        except Exception as exc:
            await websocket.send_json({"type": "error", "error": str(exc)})

    async def _run_turn(self, websocket: WebSocket, text: str) -> None:
        task = asyncio.current_task()
        try:
            response = await asyncio.to_thread(self.workspace.respond, text)
            await websocket.send_json(
                {
                    "type": "assistant",
                    "content": response,
                    "workspace": self.workspace.snapshot(),
                }
            )
        except TurnCancelledError:
            await websocket.send_json(
                {"type": "turn_stopped", "workspace": self.workspace.snapshot()}
            )
        except Exception as exc:
            await websocket.send_json({"type": "error", "error": str(exc)})
        finally:
            if websocket.scope.get("turn_task") is task:
                websocket.scope["turn_task"] = None

    async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
        turn = websocket.scope.get("turn_task")
        if isinstance(turn, asyncio.Task) and not turn.done():
            self.workspace.cancel_turn()
        queue = websocket.scope.get("event_queue")
        if isinstance(queue, asyncio.Queue):
            self.workspace.unbind_events(queue)
        sender = websocket.scope.get("sender")
        if isinstance(sender, asyncio.Task):
            sender.cancel()


def run_web_server(
    config: AppConfig, *, port: int | None = None, open_browser: bool | None = None
) -> None:
    host = config.web.host
    selected_port = port or config.web.port
    token = secrets.token_urlsafe(32)
    workspace = WebWorkspace(config)
    app = create_app(workspace, token)
    lease = RuntimeLease("Web", {"url": f"http://{host}:{selected_port}"})
    lease.acquire()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        try:
            sock.bind((host, selected_port))
            sock.listen(128)
        except OSError as exc:
            raise MalDroidError(f"Web port {selected_port} is unavailable: {exc}") from exc
        url = f"http://{host}:{selected_port}/?{urlencode({'token': token})}"
        should_open = config.web.open_browser if open_browser is None else open_browser
        print(f"MalDroid Web workspace: {url}", flush=True)
        print("Only this computer can access it. Press Ctrl+C to stop.", flush=True)
        if should_open:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on")
        )
        try:
            server.run(sockets=[sock])
        finally:
            workspace.stop_runtime()
    finally:
        sock.close()
        lease.release()


def _case_payload(case: Case) -> dict[str, Any]:
    state = case.state
    return {
        "case_id": case.metadata.case_id,
        "name": case.metadata.name,
        "path": str(case.root),
        "managed": case.metadata.managed,
        "created_at": case.metadata.created_at,
        "last_opened_at": case.metadata.last_opened_at,
        "profile": state.active_profile,
        "findings": [item.model_dump(mode="json") for item in state.findings],
        "todos": [item.model_dump(mode="json") for item in state.todos],
        "notes": [item.model_dump(mode="json") for item in state.notes],
        "checkpoints": [item.model_dump(mode="json") for item in state.checkpoints],
        "sessions": state.sessions,
        "summary": state.summary,
    }


def _safe_config(config: AppConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def _tool_data(payload: dict[str, Any], case: Case) -> dict[str, Any]:
    payload["case"] = {"case_id": case.metadata.case_id, "name": case.metadata.name}
    return payload


def _json(payload: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=_security_headers())


def _security_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
