"""Explicit self-update from MalDroid's official GitHub repository."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from maldroid.exceptions import MalDroidError

OFFICIAL_REPOSITORY = "https://github.com/yayaya142/maldroid.git"


@dataclass(frozen=True)
class UpdateResult:
    commit: str
    repository: str = OFFICIAL_REPOSITORY


def update_from_official_repository() -> UpdateResult:
    """Clone, install, and always remove the temporary source checkout."""
    git = shutil.which("git")
    if git is None:
        raise MalDroidError("Git is required for updates. Install git, then run 'maldroid update'.")
    with tempfile.TemporaryDirectory(prefix="maldroid-update-") as temporary:
        checkout = Path(temporary) / "maldroid"
        _run(
            [
                git,
                "clone",
                "--depth",
                "1",
                "--branch",
                "main",
                "--single-branch",
                OFFICIAL_REPOSITORY,
                str(checkout),
            ],
            "download the latest MalDroid source",
        )
        commit_process = _run(
            [git, "-C", str(checkout), "rev-parse", "--short", "HEAD"],
            "identify the downloaded version",
            capture_output=True,
        )
        installer = checkout / "install.sh"
        if not installer.is_file():
            raise MalDroidError("The downloaded repository does not contain install.sh.")
        environment = os.environ.copy()
        environment["PYTHON"] = str(getattr(sys, "_base_executable", sys.executable))
        _run(
            [str(installer), "--upgrade"],
            "install the MalDroid update",
            cwd=checkout,
            env=environment,
        )
        return UpdateResult(commit=commit_process.stdout.strip())


def _run(
    command: list[str],
    action: str,
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture_output,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        raise MalDroidError(f"Could not {action} (exit code {exc.returncode}).") from exc
