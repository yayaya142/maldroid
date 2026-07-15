"""Cross-process lease preventing multiple heavy MalDroid workspaces."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from filelock import FileLock, Timeout

from maldroid.exceptions import MalDroidError
from maldroid.io_utils import atomic_write_json
from maldroid.paths import data_directory


class RuntimeLease:
    """Hold one global MalDroid runtime lease until the process shuts down."""

    def __init__(self, mode: str, details: dict[str, Any] | None = None) -> None:
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(directory / "runtime.lock")
        self.metadata_path = directory / "runtime.json"
        self.mode = mode
        self.details = details or {}
        self.acquired = False

    def acquire(self) -> RuntimeLease:
        try:
            self.lock.acquire(timeout=0)
        except Timeout as exc:
            owner = self._owner()
            label = owner.get("mode", "another MalDroid workspace")
            pid = owner.get("pid")
            suffix = f" (PID {pid})" if pid else ""
            raise MalDroidError(
                f"MalDroid {label}{suffix} is already running. Close it before starting "
                f"{self.mode}. Only one CLI, Web, or update operation may run at a time."
            ) from exc
        self.acquired = True
        atomic_write_json(
            self.metadata_path,
            {
                "mode": self.mode,
                "pid": os.getpid(),
                "started_at": datetime.now().astimezone().isoformat(),
                **self.details,
            },
        )
        return self

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            if self.metadata_path.exists():
                self.metadata_path.unlink()
        finally:
            self.lock.release()
            self.acquired = False

    def _owner(self) -> dict[str, Any]:
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def __enter__(self) -> RuntimeLease:
        return self.acquire()

    def __exit__(self, *_args: object) -> None:
        self.release()
