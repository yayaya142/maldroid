from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from rich.text import Text
from typer.testing import CliRunner

import maldroid.cli as cli
import maldroid.process_manager as process_manager_module
from maldroid.config import AppConfig
from maldroid.exceptions import ServerError
from maldroid.llama_adapter import ServerCommand
from maldroid.process_manager import (
    LlamaServerProcess,
    ShutdownRequested,
    shutdown_signal_handlers,
)


def test_typer_commands_are_not_consumed_as_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MALDROID_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "llama-server" in result.stdout
    tools = runner.invoke(cli.app, ["tools", "--profile", "generic"])
    assert tools.exit_code == 0
    assert "MalDroid_read_file_range" in tools.stdout


def test_cases_opens_configured_folder_and_list_remains_available(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_directory = Path(app_config.general.cases_directory)
    monkeypatch.setattr(cli, "load_config", lambda: app_config)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command: list[str], **_kwargs: object) -> None:
            launched.append(command)

    monkeypatch.setattr(cli.subprocess, "Popen", DummyProcess)
    runner = CliRunner()

    opened = runner.invoke(cli.app, ["cases"])
    listed = runner.invoke(cli.app, ["cases", "--list"])

    assert opened.exit_code == 0
    assert launched == [["/usr/bin/open", str(cases_directory)]]
    assert "Opened cases folder" in opened.stdout
    assert listed.exit_code == 0
    assert "Case ID" in listed.stdout


def test_shutdown_signal_handlers_restore_previous_handler() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(ShutdownRequested, match="signal"), shutdown_signal_handlers():
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGTERM) == previous


def test_polished_help_version_and_mcp_client_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MALDROID_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()

    version = runner.invoke(cli.app, ["--version"])
    assert version.exit_code == 0
    assert version.stdout.strip() == "MalDroid 0.1.0"

    help_result = runner.invoke(cli.app, ["help", "mcp", "serve"])
    assert help_result.exit_code == 0
    plain_help = Text.from_ansi(help_result.stdout).plain
    assert "One-run fixed" in plain_help
    assert "--port" in plain_help

    client = runner.invoke(cli.app, ["mcp", "client-config"])
    assert client.exit_code == 0
    payload = json.loads(client.stdout)
    assert payload["mcpServers"]["maldroid"]["url"] == "http://127.0.0.1:8765/mcp"

    doctor = runner.invoke(cli.app, ["doctor", "--json"])
    assert doctor.exit_code == 0
    diagnostics = json.loads(doctor.stdout)
    assert diagnostics["version"] == "0.1.0"
    assert {item["name"] for item in diagnostics["checks"]} >= {
        "Python",
        "llama-server",
        "MCP transport",
    }

    profiles = runner.invoke(cli.app, ["profiles", "--json"])
    assert profiles.exit_code == 0
    assert {item["name"] for item in json.loads(profiles.stdout)} >= {
        "generic",
        "react-native",
    }


def test_external_mcp_cli_add_list_history_and_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(cli.ExternalMcpClient, "list_tools", lambda self: [])
    runner = CliRunner()

    added = runner.invoke(
        cli.app,
        ["mcp", "add", "http://127.0.0.1:8766/mcp", "--name", "ghidra"],
    )
    assert added.exit_code == 0
    assert "Saved MCP server" in added.stdout

    listed = runner.invoke(cli.app, ["mcp", "list", "--json"])
    assert listed.exit_code == 0
    payload = json.loads(listed.stdout)
    assert payload["servers"][0]["nickname"] == "ghidra"

    history = runner.invoke(cli.app, ["mcp", "history", "--json"])
    assert history.exit_code == 0
    assert {event["action"] for event in json.loads(history.stdout)["events"]} >= {"add", "test"}

    removed = runner.invoke(cli.app, ["mcp", "remove", "ghidra", "--yes"])
    assert removed.exit_code == 0
    assert json.loads(runner.invoke(cli.app, ["mcp", "list", "--json"]).stdout)["servers"] == []


def test_config_cli_discovery_set_validate_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MALDROID_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()

    path_result = runner.invoke(cli.app, ["config", "path"])
    assert path_result.exit_code == 0
    assert path_result.stdout.strip().endswith("config.toml")

    updated = runner.invoke(cli.app, ["config", "set", "mcp.preferred_port", "9000"])
    assert updated.exit_code == 0
    assert "mcp.preferred_port = 9000" in updated.stdout

    fetched = runner.invoke(cli.app, ["config", "get", "mcp.preferred_port", "--json"])
    assert fetched.exit_code == 0
    assert json.loads(fetched.stdout)["value"] == 9000

    valid = runner.invoke(cli.app, ["config", "validate"])
    assert valid.exit_code == 0
    assert "http://127.0.0.1:9000/mcp" in valid.stdout

    reset = runner.invoke(cli.app, ["config", "reset", "mcp.preferred_port", "--yes"])
    assert reset.exit_code == 0
    assert "8765" in reset.stdout


def test_first_time_config_wizard_explains_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MALDROID_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()

    result = runner.invoke(cli.app, ["config", "init"], input="\n\n\n\n\n\n")

    assert result.exit_code == 0, result.output
    plain_output = Text.from_ansi(result.stdout).plain
    assert "MalDroid first-time setup" in plain_output
    assert "Press Enter to accept" in plain_output
    assert "Keep API-key authentication disabled?" in plain_output
    assert "API authentication: disabled" in plain_output
    assert "WebUI: http://127.0.0.1:7575" in plain_output
    assert "Built-in llama.cpp tools: all enabled" in plain_output
    shown = runner.invoke(cli.app, ["config", "get", "llama.api_key_enabled", "--json"])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["value"] is False


def test_first_time_config_wizard_n_enables_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MALDROID_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()

    result = runner.invoke(cli.app, ["config", "init"], input="\n\n\n\nn\n\n")

    assert result.exit_code == 0, result.output
    assert "API authentication: enabled" in Text.from_ansi(result.stdout).plain
    shown = runner.invoke(cli.app, ["config", "get", "llama.api_key_enabled", "--json"])
    assert json.loads(shown.stdout)["value"] is True


@pytest.mark.parametrize(
    ("arguments", "inserted"),
    [
        ([], None),
        (["/tmp/case"], "open"),
        (["-c", "8192"], "new"),
        (["doctor"], None),
        (["mcp", "--help"], None),
        (["help", "config"], None),
        (["--version"], None),
        (["server", "--no-open"], None),
        (["cli"], None),
        (["update"], None),
    ],
)
def test_entrypoint_rewrites_daily_syntax(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], inserted: str | None
) -> None:
    captured: list[str] = []

    def fake_app() -> None:
        captured.extend(sys.argv[1:])

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(sys, "argv", ["maldroid", *arguments])
    cli.entrypoint()
    if inserted:
        assert captured[0] == inserted
    else:
        assert captured == arguments


def test_process_manager_start_and_shutdown(
    tmp_path: Path, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_module = tmp_path / "fake_llama_server.py"
    server_module.write_text(
        "import time\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    server_script = tmp_path / "fake-llama-server"
    server_script.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(server_module))} "$@"\n',
        encoding="utf-8",
    )
    server_script.chmod(0o755)
    data = app_config.model_dump()
    data["llama"]["binary"] = str(server_script)
    data["llama"]["startup_timeout_seconds"] = 5
    config = AppConfig.model_validate(data)
    case = tmp_path / "case"
    case.mkdir()
    process = LlamaServerProcess(config, case)
    monkeypatch.setattr(process, "_wait_until_ready", lambda: None)
    process.start()
    assert process.status()["running"] is True
    assert process.status()["port"] == process.command.port
    assert process.status()["api_key_enabled"] is False
    assert process.status()["api_key"] is None
    assert process.base_url == f"http://127.0.0.1:{process.command.port}/v1"
    child_pid = process.process.pid
    terminal_close_signal = getattr(signal, "SIGHUP", signal.SIGTERM)
    try:
        with shutdown_signal_handlers():
            handler = signal.getsignal(terminal_close_signal)
            assert callable(handler)
            handler(terminal_close_signal, None)
    except ShutdownRequested:
        process.stop(graceful_seconds=1)
    assert process.status()["running"] is False
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert (case / ".maldroid" / "logs" / "llama-server.stdout.log").is_file()


def test_process_status_displays_enabled_api_key(tmp_path: Path, app_config: AppConfig) -> None:
    process = LlamaServerProcess(app_config, tmp_path)
    process.command = ServerCommand(arguments=[], port=7575, api_key="visible-test-key")
    assert process.status()["api_key_enabled"] is True
    assert process.status()["api_key"] == "visible-test-key"


def test_process_manager_health_uses_direct_loopback_http(
    tmp_path: Path, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[tuple[object, ...]] = []

    class FakeResponse:
        status = 200

        @staticmethod
        def read() -> bytes:
            return b'{"status":"ok"}'

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: int):
            requests.append(("connect", host, port, timeout))

        def request(self, method: str, path: str) -> None:
            requests.append(("request", method, path))

        @staticmethod
        def getresponse() -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            requests.append(("close",))

    class RunningProcess:
        @staticmethod
        def poll() -> None:
            return None

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(process_manager_module.http.client, "HTTPConnection", FakeConnection)
    process = LlamaServerProcess(app_config, tmp_path)
    process.process = RunningProcess()  # type: ignore[assignment]
    process.command = ServerCommand(arguments=[], port=45678, api_key="test-only")

    process._wait_until_ready()

    assert requests == [
        ("connect", "127.0.0.1", 45678, 2),
        ("request", "GET", "/v1/health"),
        ("close",),
    ]


def test_process_manager_detects_early_exit(tmp_path: Path, app_config: AppConfig) -> None:
    case = tmp_path / "case"
    case.mkdir()
    process = LlamaServerProcess(app_config, case)
    with pytest.raises(ServerError, match="exited before becoming ready"):
        process.start()


def test_installer_dry_run_does_not_write(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    environment["PYTHON"] = sys.executable
    environment["PIP_INDEX_URL"] = "https://example.invalid/simple"
    completed = subprocess.run(
        [str(root / "install.sh"), "--dry-run"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "no files were changed" in completed.stdout
    assert "public PyPI (isolated from user pip configuration)" in completed.stdout
    assert not (tmp_path / ".local" / "share" / "maldroid").exists()


def test_installer_help_is_self_contained() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [str(root / "install.sh"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "Install MalDroid into an isolated user environment" in completed.stdout
    assert "--dry-run" in completed.stdout
    assert "--upgrade" in completed.stdout


@pytest.mark.parametrize("pip_exit", [0, 7])
def test_installer_upgrade_replaces_or_restores_private_environment(
    tmp_path: Path, pip_exit: int
) -> None:
    root = Path(__file__).resolve().parents[1]
    install_root = tmp_path / ".local" / "share" / "maldroid"
    old_venv = install_root / "venv"
    old_venv.mkdir(parents=True)
    (old_venv / "old-marker").write_text("previous installation", encoding="utf-8")
    fake_python = tmp_path / "base-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then exit 0; fi\n'
        'if [ "$1" = "-m" ] && [ "$2" = "ensurepip" ]; then exit 0; fi\n'
        'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
        '  mkdir -p "$3/bin"\n'
        f"  printf '#!/bin/sh\\nexit {pip_exit}\\n' > \"$3/bin/python\"\n"
        "  printf '#!/bin/sh\\nexit 0\\n' > \"$3/bin/maldroid\"\n"
        '  chmod +x "$3/bin/python" "$3/bin/maldroid"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    environment["PYTHON"] = str(fake_python)
    completed = subprocess.run(
        [str(root / "install.sh"), "--upgrade"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    backup = install_root / "venv.previous"
    if pip_exit == 0:
        assert completed.returncode == 0, completed.stderr
        assert "Mode: update existing installation" in completed.stdout
        assert not (old_venv / "old-marker").exists()
    else:
        assert completed.returncode != 0
        assert "restoring the previous" in completed.stderr
        assert (old_venv / "old-marker").is_file()
    assert not backup.exists()


def test_uninstall_preserves_or_explicitly_removes_saved_mcp_configuration(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    config_directory = tmp_path / ".config" / "maldroid"
    config_directory.mkdir(parents=True)
    registry = config_directory / "mcp-servers.json"
    registry.write_text('{"schema_version":1,"servers":[]}\n', encoding="utf-8")

    preserved = subprocess.run(
        [str(root / "uninstall.sh")],
        cwd=root,
        env=environment,
        input="y\nn\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert preserved.returncode == 0
    assert registry.exists()

    removed = subprocess.run(
        [str(root / "uninstall.sh")],
        cwd=root,
        env=environment,
        input="y\ny\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert removed.returncode == 0
    assert not config_directory.exists()
