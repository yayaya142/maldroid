"""CLI-010: Make `maldroid cases` open the directory tests."""

import pytest
from pathlib import Path
from typer.testing import CliRunner
from maldroid.cli import app

runner = CliRunner()

def test_cases_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup mock config
    import json
    
    # Run the cases command with --json
    result = runner.invoke(app, ["cases", "--json"])
    assert result.exit_code == 0
    # It should output a JSON array (even if empty)
    data = json.loads(result.stdout)
    assert isinstance(data, list)

def test_cases_list_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(app, ["cases", "--list"])
    assert result.exit_code == 0
    assert "Case ID" in result.stdout

def test_cases_open_headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Set cases directory to tmp_path
    from maldroid.config import AppConfig
    
    def mock_load_config():
        config = AppConfig()
        config.general.cases_directory = str(tmp_path)
        return config
        
    monkeypatch.setattr("maldroid.cli.load_config", mock_load_config)
    
    # Mock shutil.which to return None so it doesn't actually open anything
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    
    result = runner.invoke(app, ["cases"])
    assert result.exit_code == 0
    assert "No file manager opener found" in result.stdout
    assert str(tmp_path) in result.stdout

def test_cases_open_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from maldroid.config import AppConfig
    import subprocess
    
    def mock_load_config():
        config = AppConfig()
        config.general.cases_directory = str(tmp_path)
        return config
        
    monkeypatch.setattr("maldroid.cli.load_config", mock_load_config)
    
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/mock-open")
    
    calls = []
    def mock_popen(*args, **kwargs):
        calls.append(args[0])
        return None
        
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    
    result = runner.invoke(app, ["cases"])
    assert result.exit_code == 0
    assert "Opened" in result.stdout
    assert len(calls) == 1
    assert calls[0] == ["/usr/bin/mock-open", str(tmp_path)]
