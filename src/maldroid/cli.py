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
from rich.panel import Panel
from rich.table import Table

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.config import (
    AppConfig,
    default_config_path,
    get_config_value,
    load_config,
    reset_config_value,
    save_config,
    set_config_value,
)
from maldroid.constants import VERSION
from maldroid.evidence_manager import EvidenceManager
from maldroid.exceptions import MalDroidError
from maldroid.investigation import InvestigationManager
from maldroid.knowledge_manager import KnowledgeManager
from maldroid.llama_adapter import build_server_command, resolve_binary
from maldroid.llama_client import LocalLlamaClient
from maldroid.logging_config import configure_case_logging
from maldroid.mcp_server import MalDroidMcpServer, McpToolClient
from maldroid.paths import PathPolicy, data_directory, expand_path
from maldroid.process_manager import (
    LlamaServerProcess,
    ShutdownRequested,
    shutdown_signal_handlers,
)
from maldroid.profiles import PROFILES, get_profile, suggest_profiles
from maldroid.session_manager import SessionManager
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext
from maldroid.tools.registry import ToolRegistry, build_registry
from maldroid.ui import InteractiveChat

app = typer.Typer(
    name="maldroid",
    help="Local, MCP-enabled static-analysis workspace for Android research.",
    epilog=(
        "[bold]Start here:[/bold] maldroid doctor → maldroid config init → "
        "maldroid open PATH\n\nUse [bold]maldroid help COMMAND[/bold] for detailed command help."
    ),
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
config_app = typer.Typer(
    help="Inspect and manage validated local configuration.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
knowledge_app = typer.Typer(
    help="Manage local research playbooks.", no_args_is_help=True, rich_markup_mode="rich"
)
mcp_app = typer.Typer(
    help="Serve and configure case-scoped MCP tools.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(config_app, name="config")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(mcp_app, name="mcp")

CONFIG_DESCRIPTIONS = {
    "general.cases_directory": "Directory where managed investigation cases are created.",
    "general.default_profile": "Profile selected for newly created cases.",
    "general.default_context_size": "Model context window used for new cases.",
    "general.evidence_mode": "Default evidence registration mode: symlink or copy.",
    "llama.binary": "Path or command name for the local llama-server executable.",
    "llama.model": "Absolute path to the local GGUF model.",
    "llama.host": "Validated loopback host for llama-server.",
    "llama.preferred_port": "Preferred llama-server port; may fall back when occupied.",
    "llama.startup_timeout_seconds": "Maximum time to wait for model-server readiness.",
    "llama.parallel": "Number of llama-server request slots.",
    "llama.keep": "Prompt tokens retained across context shifts.",
    "llama.gpu_layers": "Model layers requested for GPU offload.",
    "llama.batch_size": "llama.cpp logical batch size.",
    "llama.flash_attention": "Flash-attention mode: on, off, or auto.",
    "llama.temperature": "Sampling temperature for assistant responses.",
    "llama.max_response_tokens": "Maximum generated tokens per model response.",
    "llama.reasoning_level": "Reasoning budget: off, low, medium, high, or unlimited.",
    "llama.api_key_enabled": "Enable a random per-run key for the loopback model API.",
    "llama.ui_enabled": "Serve the built-in llama.cpp WebUI.",
    "llama.ui_mcp_proxy_enabled": "Enable the experimental WebUI-to-MCP CORS proxy.",
    "llama.built_in_tools_enabled": "Expose all llama.cpp host tools in the local WebUI.",
    "llama.chat_template_file": "Optional explicit Jinja chat-template path.",
    "llama.extra_args": "Additional validated llama-server arguments.",
    "limits.max_tool_output_characters": "Largest inline tool result before disk overflow.",
    "limits.max_search_results": "Global upper bound for search matches.",
    "limits.max_read_lines": "Global upper bound for one bounded text read.",
    "limits.max_file_tree_entries": "Global upper bound for file-tree results.",
    "limits.command_timeout_seconds": "Timeout for external tools and MCP calls.",
    "limits.max_tool_rounds": "Tool rounds per autonomous phase before checkpoint rollover.",
    "limits.max_task_phases": "Deprecated compatibility setting; phases are unlimited.",
    "limits.model_retry_attempts": "Transient model-request attempts before failing the turn.",
    "limits.auto_compact_ratio": "Context usage ratio that triggers automatic compaction.",
    "external_tools.blutter": "Optional path to an explicitly configured Blutter adapter.",
    "mcp.host": "Fixed loopback host for the Python MCP server.",
    "mcp.preferred_port": "Fixed MCP port; defaults to 8765 and never falls back.",
    "mcp.startup_timeout_seconds": "Maximum time to wait for MCP readiness.",
}


def _console(no_color: bool = False) -> Console:
    return Console(no_color=no_color)


def _emit_json(data: Any) -> None:
    """Write stable, color-free JSON for scripts and connector configuration."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")
    sys.stdout.flush()


def _version_callback(value: bool) -> None:
    if value:
        _console().print(f"MalDroid {VERSION}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed MalDroid version and exit.",
    ),
) -> None:
    """Initialize global CLI options."""


@app.command("help")
def help_command(
    command: list[str] | None = typer.Argument(
        None, help="Optional nested command, for example: mcp serve"
    ),
) -> None:
    """Show root help or detailed help for any nested command."""
    root = typer.main.get_command(app)
    node: Any = root
    context: Any = root.make_context("maldroid", [], resilient_parsing=True)
    path = command or []
    for part in path:
        if not hasattr(node, "get_command"):
            raise MalDroidError(f"Command has no subcommands: {' '.join(path)}")
        child = node.get_command(context, part)
        if child is None:
            raise MalDroidError(f"Unknown command: {' '.join(path)}")
        node = child
        context = node.make_context(part, [], parent=context, resilient_parsing=True)
    _console().print(node.get_help(context))


@app.command()
def new(
    name: str | None = typer.Argument(None, help="Optional human-readable case name."),
    profile: str = typer.Option("generic", "--profile", help="Initial static-analysis profile."),
    context_size: int | None = typer.Option(
        None, "--context-size", "-c", help="Override the configured model context size."
    ),
    model: Path | None = typer.Option(None, "--model", help="Override the GGUF model path."),
    llama_server: Path | None = typer.Option(
        None, "--llama-server", help="Override the llama-server executable."
    ),
    port: int | None = typer.Option(
        None, "--port", min=1, max=65535, help="One-run llama-server port override."
    ),
    mcp_port: int | None = typer.Option(
        None, "--mcp-port", min=1, max=65535, help="One-run fixed MCP port override."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable terminal colors."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks for unexpected failures."),
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
    path: Path = typer.Argument(help="Case directory or single evidence artifact."),
    profile: str | None = typer.Option(None, "--profile", help="Static-analysis profile."),
    copy: bool = typer.Option(
        False, "--copy", help="Copy a file into evidence instead of symlinking."
    ),
    name: str | None = typer.Option(None, "--name", help="Name for a newly created case."),
    context_size: int | None = typer.Option(
        None, "--context-size", "-c", help="Override the configured model context size."
    ),
    model: Path | None = typer.Option(None, "--model", help="Override the GGUF model path."),
    llama_server: Path | None = typer.Option(
        None, "--llama-server", help="Override the llama-server executable."
    ),
    port: int | None = typer.Option(
        None, "--port", min=1, max=65535, help="One-run llama-server port override."
    ),
    mcp_port: int | None = typer.Option(
        None, "--mcp-port", min=1, max=65535, help="One-run fixed MCP port override."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable terminal colors."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks for unexpected failures."),
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


@app.command(epilog="Example: maldroid cases --json")
def cases(
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON output."),
) -> None:
    """List known cases and compact investigation counts."""
    console = _console()
    manager = CaseManager(load_config())
    records = manager.list_cases()
    if json_output:
        _emit_json(records)
        return
    table = Table(
        "Name", "Case ID", "Path", "Created", "Last opened", "Profile", "Findings", "Open TODO"
    )
    for item in records:
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


@app.command(epilog="Example: maldroid profiles --json")
def profiles(
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON output."),
) -> None:
    """List profiles and implementation status."""
    if json_output:
        _emit_json([vars(profile) for profile in PROFILES.values()])
        return
    table = Table("Profile", "Status", "Instruction")
    for profile in PROFILES.values():
        table.add_row(profile.name, profile.status, profile.instruction)
    _console().print(table)


@app.command("tools", epilog="Example: maldroid tools --profile react-native --json")
def tools_command(
    profile: str = typer.Option("generic", "--profile", help="Profile whose tool set to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit names and schemas as JSON."),
) -> None:
    """List exactly which tools a profile exposes."""
    get_profile(profile)
    registry = build_registry()
    if json_output:
        _emit_json(
            {
                "profile": profile,
                "names": registry.names(profile),
                "tools": registry.schemas(profile),
            }
        )
    else:
        _console().print("\n".join(registry.names(profile)))


@mcp_app.command(
    "serve",
    epilog=(
        "Examples:\n  maldroid mcp serve /path/to/case\n"
        "  maldroid mcp serve /path/to/case --port 8765 --json"
    ),
)
def mcp_serve(
    case_path: Path | None = typer.Argument(
        None, help="Existing MalDroid case; defaults to the most recent case."
    ),
    profile: str | None = typer.Option(
        None, "--profile", help="Persist this active profile before serving."
    ),
    port: int | None = typer.Option(
        None, "--port", min=1, max=65535, help="One-run fixed MCP port override."
    ),
    json_output: bool = typer.Option(False, "--json", help="Print startup metadata as JSON."),
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
            _emit_json(
                {
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
            with shutdown_signal_handlers():
                server.wait()
        except ShutdownRequested:
            pass
        finally:
            server.stop()

    _run_guarded(run, False, _console())


@mcp_app.command("client-config")
def mcp_client_config(
    name: str = typer.Option("maldroid", "--name", help="Connector name in the generated config."),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
) -> None:
    """Print a ready-to-paste MCP client configuration."""
    config = load_config()
    selected_port = port or config.mcp.preferred_port
    _emit_json(
        {
            "mcpServers": {
                name: {
                    "type": "http",
                    "url": f"http://{config.mcp.host}:{selected_port}/mcp",
                }
            }
        }
    )


@app.command(epilog="Examples: maldroid doctor --json | maldroid doctor --model-tool-test")
def doctor(
    show_command: bool = typer.Option(
        False, "--show-command", help="Show the secret-redacted llama-server command."
    ),
    model_tool_test: bool = typer.Option(
        False, "--model-tool-test", help="Run the real structured tool-call compatibility test."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit diagnostic checks as JSON."),
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
            "Model API authentication",
            "ok",
            "random per-run key" if config.llama.api_key_enabled else "disabled on loopback",
        )
    )
    checks.append(
        (
            "llama.cpp WebUI",
            "ok" if config.llama.ui_enabled else "warning",
            "enabled" if config.llama.ui_enabled else "disabled",
        )
    )
    checks.append(
        (
            "WebUI MCP proxy",
            "warning" if config.llama.ui_mcp_proxy_enabled else "ok",
            "enabled (experimental)" if config.llama.ui_mcp_proxy_enabled else "disabled",
        )
    )
    checks.append(
        (
            "llama.cpp built-in tools",
            "warning" if config.llama.built_in_tools_enabled else "ok",
            "all enabled with host permissions"
            if config.llama.built_in_tools_enabled
            else "disabled",
        )
    )
    checks.append(
        (
            "MCP transport",
            "ok",
            f"streamable-http on {config.mcp.host}:{config.mcp.preferred_port}/mcp",
        )
    )
    if json_output and model_tool_test:
        raise MalDroidError("--json cannot be combined with the interactive --model-tool-test.")
    if json_output:
        payload: dict[str, Any] = {
            "version": VERSION,
            "checks": [
                {"name": check, "status": status, "details": details}
                for check, status, details in checks
            ],
        }
        if show_command:
            payload["llama_server_command"] = build_server_command(config).display()
        _emit_json(payload)
    else:
        table = Table("Check", "Status", "Details")
        for check, status, details in checks:
            table.add_row(check, status, details)
        console.print(table)
    if show_command and not json_output:
        command = build_server_command(config)
        console.print(command.display())
    if model_tool_test:
        _doctor_model_tool_test(config, console)


@config_app.command(
    "init",
    epilog="Run this once after installation. Existing values are offered as prompt defaults.",
)
def config_init() -> None:
    """Run first-use configuration and save a validated TOML file."""
    current = load_config()
    console = _console()
    detected_binary = shutil.which("llama-server")
    binary_default = detected_binary or current.llama.binary
    console.print(
        Panel.fit(
            "This wizard connects MalDroid to your local llama.cpp installation.\n"
            "Press Enter to accept any value shown in brackets.",
            title="MalDroid first-time setup",
        )
    )
    console.print("\n[bold]1/5 — llama-server[/bold]")
    console.print("The executable that starts your local model server.")
    if detected_binary:
        console.print(f"Detected automatically: [green]{detected_binary}[/green]")
    binary = typer.prompt("llama-server path", default=binary_default)

    console.print("\n[bold]2/5 — Model[/bold]")
    console.print("The complete path to your local .gguf model file.")
    model = typer.prompt("GGUF model path", default=current.llama.model)

    console.print("\n[bold]3/5 — Cases[/bold]")
    console.print("New investigation folders will be created here.")
    cases_directory = typer.prompt("Cases directory", default=current.general.cases_directory)

    console.print("\n[bold]4/5 — Model context[/bold]")
    console.print("Keep 65536 unless your model or hardware requires a smaller value.")
    context_size = typer.prompt(
        "Default context size", default=current.general.default_context_size, type=int
    )

    console.print("\n[bold]5/5 — Local access[/bold]")
    console.print(
        "API-key authentication is normally unnecessary because the server only listens on "
        "this computer. Keeping it disabled allows direct WebUI and API access."
    )
    keep_api_key_disabled = typer.confirm("Keep API-key authentication disabled?", default=True)
    api_key_enabled = not keep_api_key_disabled
    console.print(
        "\n[dim]Advanced arguments are optional. Most users should leave this empty.[/dim]"
    )
    existing_extra = shlex.join(current.llama.extra_args)
    extra = typer.prompt("Additional llama-server arguments", default=existing_extra)
    data = current.model_dump()
    data["llama"]["binary"] = binary
    data["llama"]["model"] = model
    data["llama"]["api_key_enabled"] = api_key_enabled
    data["llama"]["extra_args"] = shlex.split(extra) if extra else []
    data["general"]["cases_directory"] = cases_directory
    data["general"]["default_context_size"] = context_size
    config = AppConfig.model_validate(data)
    target = save_config(config)
    console.print("\n[green bold]Configuration saved.[/green bold]")
    console.print(f"File: {target}")
    console.print(
        "API authentication: "
        + ("enabled (a new key is generated per run)" if api_key_enabled else "disabled")
    )
    console.print(f"WebUI: http://{config.llama.host}:{config.llama.preferred_port}")
    console.print("WebUI MCP proxy: enabled")
    console.print(
        "Built-in llama.cpp tools: all enabled (host shell and files; select tools in the WebUI)."
    )
    console.print("Run [bold]maldroid doctor[/bold] to verify the complete setup.")


@config_app.command("show", epilog="Use --json for scripts and support bundles.")
def config_show(
    json_output: bool = typer.Option(False, "--json", help="Emit the complete config as JSON."),
) -> None:
    """Display every effective value, default, and plain-language description."""
    config = load_config()
    if json_output:
        _emit_json(config.model_dump(mode="json"))
        return
    defaults = AppConfig()
    console = _console()
    console.print(f"Configuration file: {default_config_path()}")
    for section, values in config.model_dump(mode="json").items():
        table = Table("Setting", "Effective value", "State", "Purpose", title=f"[{section}]")
        for key, value in values.items():
            dotted_key = f"{section}.{key}"
            default = get_config_value(defaults, dotted_key)
            table.add_row(
                key,
                _display_config_value(value),
                "default" if value == default else "custom",
                CONFIG_DESCRIPTIONS.get(dotted_key, ""),
            )
        console.print(table)


@config_app.command("get")
def config_get(
    key: str = typer.Argument(help="Configuration key in section.key form."),
    json_output: bool = typer.Option(False, "--json", help="Emit key metadata as JSON."),
) -> None:
    """Read one effective configuration value."""
    config = load_config()
    value = get_config_value(config, key)
    if json_output:
        _emit_json(
            {
                "key": key,
                "value": value,
                "default": get_config_value(AppConfig(), key),
                "description": CONFIG_DESCRIPTIONS.get(key, ""),
            }
        )
    else:
        _console().print(_display_config_value(value))


@config_app.command("path")
def config_path() -> None:
    """Print the configuration file path without creating it."""
    _console().print(str(default_config_path()))


@config_app.command("validate")
def config_validate() -> None:
    """Validate the saved configuration and security constraints."""
    config = load_config()
    _console().print(
        f"Configuration is valid: {default_config_path()}\n"
        f"MCP endpoint: http://{config.mcp.host}:{config.mcp.preferred_port}/mcp"
    )


@config_app.command("set", epilog="Example: maldroid config set mcp.preferred_port 8765")
def config_set(
    key: str = typer.Argument(help="Configuration key in section.key form."),
    value: str = typer.Argument(help="New value; quote lists or paths containing spaces."),
) -> None:
    """Set one section.key value after validation."""
    config = set_config_value(load_config(), key, value)
    target = save_config(config)
    _console().print(f"Updated {key} = {_display_config_value(get_config_value(config, key))}")
    _console().print(f"Saved: {target}")


@config_app.command("reset")
def config_reset(
    key: str = typer.Argument(help="Configuration key in section.key form."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Reset without confirmation."),
) -> None:
    """Reset one configuration key to its packaged default."""
    config = load_config()
    current = get_config_value(config, key)
    default = get_config_value(AppConfig(), key)
    if not yes:
        typer.confirm(
            f"Reset {key} from {_display_config_value(current)} to "
            f"{_display_config_value(default)}?",
            abort=True,
        )
    updated = reset_config_value(config, key)
    target = save_config(updated)
    _console().print(f"Reset {key} = {_display_config_value(default)}")
    _console().print(f"Saved: {target}")


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
    _emit_json(manager.list_documents())


@knowledge_app.command("reindex")
def knowledge_reindex() -> None:
    """Rebuild the local FTS5 knowledge index for the latest case."""
    manager, _ = _knowledge_manager_for_cli()
    _emit_json(manager.reindex())


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
        with shutdown_signal_handlers():
            logger.info("Starting local llama-server")
            command = server.start(case.state.context_size, port, explicit_port=port is not None)
            client = LocalLlamaClient(
                server.base_url,
                command.api_key,
                Path(config.llama.model).name,
                config.llama.temperature,
                config.llama.max_response_tokens,
                config.llama.reasoning_level,
            )
            registry, local_dispatcher = _build_tool_runtime(config, case, manager)
            investigation = local_dispatcher.context.investigation
            mcp_server = MalDroidMcpServer(
                config,
                registry,
                local_dispatcher,
                model_server_port=command.port,
            )
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
    except ShutdownRequested as exc:
        logger.info("Orderly shutdown requested by signal %s", exc.signum)
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
        headers = {"Authorization": f"Bearer {command.api_key}"} if command.api_key else {}
        request = urllib.request.Request(
            server.base_url.removesuffix("/v1") + "/props", headers=headers
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
            config.llama.reasoning_level,
        )
        schema = {
            "type": "function",
            "function": {
                "name": "MalDroid_doctor_probe",
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
                "content": 'Call MalDroid_doctor_probe with items ["alpha", "{braces}"] and metadata {"status":"ok"}.',
            },
        ]
        first = client.complete(messages, [schema])
        if len(first.tool_calls) != 1 or first.tool_calls[0].name != "MalDroid_doctor_probe":
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


def _display_config_value(value: Any) -> str:
    if value is None:
        return "<not set>"
    if isinstance(value, str):
        return value or "<empty>"
    return json.dumps(value, ensure_ascii=False)


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
        "help",
    }
    arguments = sys.argv[1:]
    global_options = {
        "--version",
        "--install-completion",
        "--show-completion",
        "--help",
        "-h",
    }
    if not arguments:
        sys.argv.append("new")
    elif arguments[0] not in commands and arguments[0] not in global_options:
        sys.argv.insert(1, "new" if arguments[0].startswith("-") else "open")
    try:
        app()
    except (MalDroidError, ValidationError, OSError) as exc:
        _console().print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    entrypoint()
