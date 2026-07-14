"""Atomic local persistence helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from filelock import FileLock


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Atomically replace a text file while serializing concurrent writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    """Serialize JSON deterministically and atomically."""
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, value: Any) -> None:
    """Append one JSON object to an audit stream under a file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock")
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
