"""MalDroid command-line interface and daily case workflow."""

from __future__ import annotations

import json
import shlex
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.config import (
    AppConfig,
    load_config,
    save_config,
    set_config_value,
)
from maldroid.evidence_manager import EvidenceManager
from maldroid.exceptions import MalDroidError
from maldroid.investigation import InvestigationManager
from maldroid.knowledge_manager import KnowledgeManager
from maldroid.llama_adapter import build_server_command, resolve_binary
from maldroid.llama_client import LocalLlamaClient
from maldroid.logging_config import configure_case_logging
from maldroid.mcp_server import MalDroidMcpServer, McpToolClient
from maldroid.paths import PathPolicy, data_directory, expand_path
from maldroid.process_manager import LlamaServerProcess
from maldroid.profiles import PROFILES, get_profile, suggest_profiles
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import ToolRegistry, build_registry
from maldroid.ui import InteractiveChat

app = typer.Typer(
    name="maldroid",
    help="Local static-analysis assistant for Android malware research.",
)
config_app = typer.Typer(help="Manage validated local configuration.")
knowledge_app = typer.Typer(help="Manage local research playbooks.")
mcp_app = typer.Typer(help="Expose case-scoped MalDroid tools through MCP.")
app.add_typer(config_app, name="config")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(mcp_app, name="mcp")


def _console(no_color: bool = False) -> Console:
    return Console(no_color=no_color)


@app.command()
def new(
    name: str | None = typer.Argument(None),
    profile: str = typer.Option("generic", "--profile"),
    context_size: int | None = typer.Option(None, "--context-size", "-c"),
    model: Path | None = typer.Option(None, "--model"),
    llama_server: Path | None = typer.Option(None, "--llama-server"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    mcp_port: int | None = typer.Option(None, "--mcp-port", min=1, max=65535),
    no_color: bool = typer.Option(False, "--no-color"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Create a new managed case and start the assistant."""
    _run_guarded(
        lambda: _launch(
            None,
            name,
            profile,
            context_size,
            False,
            model,
            llama_server,
            port,
            mcp_port,
            no_color,
        ),
        debug,
        _console(no_color),
    )


@app.command("open")
def open_command(
    path: Path,
    profile: str | None = typer.Option(None, "--profile"),
    copy: bool = typer.Option(False, "--copy"),
    name: str | None = typer.Option(None, "--name"),
    context_size: int | None = typer.Option(None, "--context-size", "-c"),
    model: Path | None = typer.Option(None, "--model"),
    llama_server: Path | None = typer.Option(None, "--llama-server"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    mcp_port: int | None = typer.Option(None, "--mcp-port", min=1, max=65535),
    no_color: bool = typer.Option(False, "--no-color"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Open a directory or register a single artifact in a new case."""
    _run_guarded(
        lambda: _launch(
            path,
            name,
            profile,
            context_size,
            copy,
            model,
            llama_server,
            port,
            mcp_port,
            no_color,
        ),
        debug,
        _console(no_color),
    )


@app.command()
def resume() -> None:
    """Resume the most recently opened case."""
    _run_guarded(lambda: _launch_resume(), False, _console())


@app.command()
def cases() -> None:
    """List known cases and compact investigation counts."""
    console = _console()
    manager = CaseManager(load_config())
    table = Table(
        "Name", "Case ID", "Path", "Created", "Last opened", "Profile", "Findings", "Open TODO"
    )
    for item in manager.list_cases():
        table.add_row(
            str(item["name"]),
            str(item["case_id"]),
            str(item["path"]),
            str(item["created_at"]),
            str(item["last_opened_at"]),
            str(item["profile"]),
            str(item["findings"]),
            str(item["open_todos"]),
        )
    console.print(table)


@app.command()
def profiles() -> None:
    """List profiles and implementation status."""
    table = Table("Profile", "Status", "Instruction")
    for profile in PROFILES.values():
        table.add_row(profile.name, profile.status, profile.instruction)
    _console().print(table)


@app.command("tools")
def tools_command(profile: str = typer.Option("generic", "--profile")) -> None:
    """List exactly which tools a profile exposes."""
    get_profile(profile)
    registry = build_registry()
    _console().print("\n".join(registry.names(profile)))


@mcp_app.command("serve")
def mcp_serve(
    case_path: Path | None = typer.Argument(None),
    profile: str | None = typer.Option(None, "--profile"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Serve the latest or selected case through loopback MCP Streamable HTTP."""

    def run() -> None:
        config = load_config()
        manager = CaseManager(config)
        case = manager.open(expand_path(case_path)) if case_path else manager.resume()
        if profile:
            selected = get_profile(profile)
            if selected.status != "implemented":
                raise MalDroidError(f"Profile is not implemented: {profile}")
            case.state.active_profile = profile
            manager.save(case)
        registry, dispatcher = _build_tool_runtime(config, case, manager)
        server = MalDroidMcpServer(config, registry, dispatcher)
        endpoint = server.start(port)
        console = _console()
        if json_output:
            console.print_json(
                data={
                    "status": "ready",
                    "transport": "streamable-http",
                    "host": server.host,
                    "port": server.port,
                    "endpoint": endpoint,
                    "case": str(case.root),
                    "profile": case.state.active_profile,
                }
            )
        else:
            console.print("[bold]MalDroid MCP server is ready[/bold]")
            console.print(f"Endpoint: {endpoint}")
            console.print(f"Port: {server.port}")
            console.print("Transport: streamable-http")
            console.print(f"Case: {case.root}")
            console.print(f"Profile: {case.state.active_profile}")
            console.print("Press Ctrl-C to stop.")
        try:
            server.wait()
        finally:
            server.stop()

    _run_guarded(run, False, _console())


@app.command()
def doctor(
    show_command: bool = typer.Option(False, "--show-command"),
    model_tool_test: bool = typer.Option(False, "--model-tool-test"),
) -> None:
    """Diagnose local dependencies and optionally verify real model tool calling."""
    console = _console()
    config = load_config()
    checks: list[tuple[str, str, str]] = []
    checks.append(
        ("Python", "ok" if sys.version_info >= (3, 11) else "error", sys.version.split()[0])
    )
    checks.append(("Platform", "ok", sys.platform))
    checks.append(
        ("ripgrep", "ok" if shutil.which("rg") else "warning", shutil.which("rg") or "not found")
    )
    try:
        binary = resolve_binary(config.llama.binary)
        checks.append(("llama-server", "ok", str(binary)))
    except MalDroidError as exc:
        checks.append(("llama-server", "error", str(exc)))
    model_path = expand_path(config.llama.model)
    checks.append(("GGUF model", "ok" if model_path.is_file() else "error", str(model_path)))
    checks.append(("Host boundary", "ok", config.llama.host))
    checks.append(
        (
            "MCP transport",
            "ok",
            f"streamable-http on {config.mcp.host}:{config.mcp.preferred_port}/mcp",
        )
    )
    table = Table("Check", "Status", "Details")
    for check, status, details in checks:
        table.add_row(check, status, details)
    console.print(table)
    if show_command:
        command = build_server_command(config)
        console.print(command.display())
    if model_tool_test:
        _doctor_model_tool_test(config, console)


@config_app.command("init")
def config_init() -> None:
    """Run first-use configuration and save a validated TOML file."""
    current = load_config()
    binary = typer.prompt("llama-server executable", default=current.llama.binary)
    model = typer.prompt("GGUF model path", default=current.llama.model)
    cases_directory = typer.prompt("Cases directory", default=current.general.cases_directory)
    context_size = typer.prompt(
        "Default context size", default=current.general.default_context_size, type=int
    )
    extra = typer.prompt("Optional extra llama-server arguments", default="")
    data = current.model_dump()
    data["llama"]["binary"] = binary
    data["llama"]["model"] = model
    data["llama"]["extra_args"] = shlex.split(extra) if extra else []
    data["general"]["cases_directory"] = cases_directory
    data["general"]["default_context_size"] = context_size
    config = AppConfig.model_validate(data)
    target = save_config(config)
    _console().print(f"Saved configuration: {target}")


@config_app.command("show")
def config_show() -> None:
    """Display effective validated configuration."""
    _console().print_json(data=load_config().model_dump())


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set one section.key value after validation."""
    config = set_config_value(load_config(), key, value)
    target = save_config(config)
    _console().print(f"Updated {key} in {target}")


@knowledge_app.command("add")
def knowledge_add(
    path: Path,
    profile: str = typer.Option("generic", "--profile"),
    copy: bool = typer.Option(True, "--copy/--no-copy"),
) -> None:
    """Copy a Markdown playbook into local user knowledge."""
    get_profile(profile)
    manager, _ = _knowledge_manager_for_cli()
    destination = manager.add(path, profile, copy)
    _console().print(f"Added knowledge: {destination}")


@knowledge_app.command("list")
def knowledge_list() -> None:
    """List indexed knowledge documents."""
    manager, _ = _knowledge_manager_for_cli()
    if not manager.list_documents():
        manager.reindex()
    _console().print_json(data=manager.list_documents())


@knowledge_app.command("reindex")
def knowledge_reindex() -> None:
    """Rebuild the local FTS5 knowledge index for the latest case."""
    manager, _ = _knowledge_manager_for_cli()
    _console().print_json(data=manager.reindex())


def _launch(
    path: Path | None,
    name: str | None,
    profile: str | None,
    context_size: int | None,
    copy: bool,
    model: Path | None,
    llama_server: Path | None,
    port: int | None,
    mcp_port: int | None,
    no_color: bool,
) -> None:
    config = _config_with_overrides(load_config(), model, llama_server)
    manager = CaseManager(config)
    if path is None:
        case = manager.create(name)
    else:
        target = expand_path(path)
        if target.is_dir():
            case = (
                manager.open(target)
                if (target / ".maldroid" / "case.toml").exists()
                else manager.initialize_existing(target, name)
            )
        elif target.is_file():
            case = manager.create(name)
            EvidenceManager(manager).register(case, target, "copy" if copy else "symlink")
        else:
            raise MalDroidError(f"The requested path does not exist: {target}")
        suggestions = suggest_profiles(target)
        if suggestions and not profile:
            _console(no_color).print("Suggested profile(s): " + ", ".join(suggestions))
    selected_profile = profile or case.state.active_profile or config.general.default_profile
    profile_definition = get_profile(selected_profile)
    if profile_definition.status != "implemented":
        raise MalDroidError(f"Profile is planned but not implemented in V1: {selected_profile}")
    case.state.active_profile = selected_profile
    case.state.context_size = context_size or config.general.default_context_size
    case.state.model_path = config.llama.model
    manager.save(case)
    _run_case(config, case, manager, port, mcp_port, no_color)


def _launch_resume() -> None:
    config = load_config()
    manager = CaseManager(config)
    case = manager.resume()
    _run_case(config, case, manager, None, None, False)


def _run_case(
    config: AppConfig,
    case: Case,
    manager: CaseManager,
    port: int | None,
    mcp_port: int | None,
    no_color: bool,
) -> None:
    console = _console(no_color)
    logger = configure_case_logging(case.root)
    server = LlamaServerProcess(config, case.root)
    mcp_server: MalDroidMcpServer | None = None
    sessions: SessionManager | None = None
    agent: MalDroidAgent | None = None
    try:
        logger.info("Starting local llama-server")
        command = server.start(case.state.context_size, port, explicit_port=port is not None)
        client = LocalLlamaClient(
            server.base_url,
            command.api_key,
            Path(config.llama.model).name,
            config.llama.temperature,
            config.llama.max_response_tokens,
        )
        registry, local_dispatcher = _build_tool_runtime(config, case, manager)
        investigation = local_dispatcher.context.investigation
        mcp_server = MalDroidMcpServer(config, registry, local_dispatcher)
        mcp_endpoint = mcp_server.start(mcp_port)
        console.print(f"MCP endpoint: {mcp_endpoint}")
        dispatcher = McpToolClient(
            mcp_endpoint, timeout_seconds=config.limits.command_timeout_seconds
        )
        previous = SessionManager.load_latest_summary(case)
        sessions = SessionManager(case, manager)
        agent = MalDroidAgent(config, case, client, registry, dispatcher, sessions, previous)
        chat = InteractiveChat(
            console,
            case,
            manager,
            investigation,
            server,
            agent,
            registry,
            dispatcher,
            mcp_endpoint,
        )
        chat.run()
        try:
            agent.compact()
        except Exception as exc:
            sessions.save_summary(case.state.summary or f"Session ended. Summary failed: {exc}")
    finally:
        if mcp_server is not None:
            mcp_server.stop()
        server.stop()
        logger.info("Local llama-server stopped")


def _build_tool_runtime(
    config: AppConfig, case: Case, manager: CaseManager
) -> tuple[ToolRegistry, ToolDispatcher]:
    registry = build_registry()
    investigation = InvestigationManager(manager)
    evidence_sources = {item.case_path: item.source_resolved_path for item in case.state.evidence}
    context = ToolContext(
        config=config,
        case=case,
        case_manager=manager,
        investigation=investigation,
        path_policy=PathPolicy(case.root, evidence_sources),
    )
    return registry, ToolDispatcher(registry, context)


def _config_with_overrides(
    config: AppConfig, model: Path | None, llama_server: Path | None
) -> AppConfig:
    data = config.model_dump()
    if model:
        data["llama"]["model"] = str(expand_path(model))
    if llama_server:
        data["llama"]["binary"] = str(expand_path(llama_server))
    return AppConfig.model_validate(data)


def _doctor_model_tool_test(config: AppConfig, console: Console) -> None:
    diagnostic = data_directory() / "doctor"
    (diagnostic / ".maldroid" / "logs").mkdir(parents=True, exist_ok=True)
    server = LlamaServerProcess(config, diagnostic)
    try:
        command = server.start()
        request = urllib.request.Request(
            server.base_url.removesuffix("/v1") + "/props",
            headers={"Authorization": f"Bearer {command.api_key}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            props = json.loads(response.read().decode("utf-8"))
        templates = [key for key in props if "template" in key.lower()]
        console.print(f"Template properties: {templates or 'not reported'}")
        client = LocalLlamaClient(
            server.base_url,
            command.api_key,
            Path(config.llama.model).name,
            config.llama.temperature,
            config.llama.max_response_tokens,
        )
        schema = {
            "type": "function",
            "function": {
                "name": "maldroid_doctor_probe",
                "description": "Return structured values for a local compatibility test.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object", "additionalProperties": {"type": "string"}},
                    },
                    "required": ["items", "metadata"],
                    "additionalProperties": False,
                },
            },
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "Call the requested diagnostic tool exactly once."},
            {
                "role": "user",
                "content": 'Call maldroid_doctor_probe with items ["alpha", "{braces}"] and metadata {"status":"ok"}.',
            },
        ]
        first = client.complete(messages, [schema])
        if len(first.tool_calls) != 1 or first.tool_calls[0].name != "maldroid_doctor_probe":
            raise MalDroidError(
                "The model did not return a structured tool call. Configure a compatible chat template."
            )
        arguments = json.loads(first.tool_calls[0].arguments)
        if arguments.get("items") != ["alpha", "{braces}"] or arguments.get("metadata") != {
            "status": "ok"
        }:
            raise MalDroidError(f"The model returned incorrect structured arguments: {arguments}")
        messages.append(first.as_history_message())
        messages.append(
            {
                "role": "tool",
                "tool_call_id": first.tool_calls[0].id,
                "content": '{"status":"completed","data":{"accepted":true}}',
            }
        )
        final = client.complete(messages, [schema])
        if final.tool_calls or not final.content:
            raise MalDroidError("The model did not produce a final response after the tool result.")
        if first.reasoning_content:
            console.print("reasoning_content round-trip: supported")
        console.print("[green]Gemma tool-calling compatibility test passed.[/green]")
    finally:
        server.stop()


def _knowledge_manager_for_cli() -> tuple[KnowledgeManager, Case]:
    config = load_config()
    manager = CaseManager(config)
    try:
        case = manager.resume()
    except MalDroidError:
        root = data_directory() / "knowledge-case"
        root.mkdir(parents=True, exist_ok=True)
        case = manager.initialize_existing(root, "Knowledge Index")
    return KnowledgeManager(case), case


def _run_guarded(action: Any, debug: bool, console: Console) -> None:
    try:
        action()
    except (MalDroidError, ValidationError, OSError) as exc:
        if debug:
            raise
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def entrypoint() -> None:
    """Preserve `maldroid [PATH]` while keeping command names unambiguous."""
    commands = {
        "new",
        "open",
        "resume",
        "cases",
        "doctor",
        "profiles",
        "tools",
        "config",
        "knowledge",
        "mcp",
    }
    arguments = sys.argv[1:]
    if not arguments:
        sys.argv.append("new")
    elif arguments[0] not in commands and arguments[0] not in {"--help", "-h"}:
        sys.argv.insert(1, "new" if arguments[0].startswith("-") else "open")
    try:
        app()
    except (MalDroidError, ValidationError, OSError) as exc:
        _console().print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    entrypoint()
