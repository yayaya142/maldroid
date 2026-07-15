from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from maldroid import cli
from maldroid.exceptions import MalDroidError
from maldroid.updater import OFFICIAL_REPOSITORY, UpdateResult, update_from_official_repository


def test_update_clones_official_main_installs_and_removes_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path | None, bool]] = []
    checkout: Path | None = None
    monkeypatch.setattr("maldroid.updater.shutil.which", lambda name: "/usr/bin/git")

    def fake_run(
        command: list[str],
        *,
        cwd: Path | None,
        check: bool,
        text: bool,
        capture_output: bool,
        env: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal checkout
        calls.append((command, cwd, capture_output))
        assert check is True
        assert text is True
        if "clone" in command:
            checkout = Path(command[-1])
            checkout.mkdir(parents=True)
            (checkout / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, stdout="abc1234\n", stderr="")
        assert command[1:] == ["--upgrade"]
        assert cwd == checkout
        assert env is not None
        assert Path(env["PYTHON"]).is_absolute()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("maldroid.updater.subprocess.run", fake_run)
    result = update_from_official_repository()

    assert result == UpdateResult(commit="abc1234")
    assert calls[0][0][1:8] == [
        "clone",
        "--depth",
        "1",
        "--branch",
        "main",
        "--single-branch",
        OFFICIAL_REPOSITORY,
    ]
    assert checkout is not None
    assert not checkout.exists()


def test_update_cleans_checkout_after_install_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    checkout: Path | None = None
    monkeypatch.setattr("maldroid.updater.shutil.which", lambda name: "/usr/bin/git")

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal checkout
        if "clone" in command:
            checkout = Path(command[-1])
            checkout.mkdir(parents=True)
            (checkout / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, stdout="abc1234\n", stderr="")
        raise subprocess.CalledProcessError(9, command)

    monkeypatch.setattr("maldroid.updater.subprocess.run", fake_run)
    with pytest.raises(MalDroidError, match="install the MalDroid update"):
        update_from_official_repository()
    assert checkout is not None
    assert not checkout.exists()


def test_update_requires_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("maldroid.updater.shutil.which", lambda name: None)
    with pytest.raises(MalDroidError, match="Git is required"):
        update_from_official_repository()


def test_update_cli_reports_new_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "update_from_official_repository", lambda: UpdateResult(commit="def5678")
    )
    monkeypatch.setattr(cli, "RuntimeLease", lambda mode: nullcontext())
    result = CliRunner().invoke(cli.app, ["update"])
    assert result.exit_code == 0
    assert "updated successfully" in result.stdout
    assert "def5678" in result.stdout
    assert "temporary source checkout was removed" in result.stdout
