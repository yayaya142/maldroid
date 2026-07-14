from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import maldroid.cli as cli
from maldroid.config import AppConfig
from maldroid.exceptions import ServerError
from maldroid.process_manager import LlamaServerProcess


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
    assert "read_file_range" in tools.stdout


@pytest.mark.parametrize(
    ("arguments", "inserted"),
    [
        ([], "new"),
        (["/tmp/case"], "open"),
        (["-c", "8192"], "new"),
        (["doctor"], None),
        (["mcp", "--help"], None),
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


def test_process_manager_health_and_shutdown(tmp_path: Path, app_config: AppConfig) -> None:
    server_script = tmp_path / "fake-llama-server"
    server_script.write_text(
        """#!/usr/bin/env python3
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = int(sys.argv[sys.argv.index('--port') + 1])
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/health', '/v1/health'):
            body = json.dumps({'status':'ok'}).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', port), Handler).serve_forever()
""",
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
    process.start()
    assert process.status()["running"] is True
    process.stop(graceful_seconds=1)
    assert process.status()["running"] is False
    assert (case / ".maldroid" / "logs" / "llama-server.stdout.log").is_file()


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
    assert not (tmp_path / ".local" / "share" / "maldroid").exists()
