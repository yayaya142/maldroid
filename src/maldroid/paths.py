"""Cross-platform application path and case-boundary enforcement."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from maldroid.exceptions import SecurityError

DEFAULT_SCAN_IGNORED_DIRECTORIES = frozenset(
    {".git", ".maldroid", ".venv", "__pycache__", "tool-output"}
)


def expand_path(value: str | Path) -> Path:
    """Expand environment variables and the user home marker."""
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).absolute()


def config_directory() -> Path:
    return expand_path(os.environ.get("MALDROID_CONFIG_DIR", "~/.config/maldroid"))


def data_directory() -> Path:
    return expand_path(os.environ.get("MALDROID_DATA_DIR", "~/.local/share/maldroid"))


def default_cases_directory() -> Path:
    return expand_path(os.environ.get("MALDROID_CASES_DIR", "~/MalDroid/cases"))


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def walk_regular_entries(
    root: Path,
    *,
    include_directories: bool = False,
    ignored_directories: frozenset[str] = DEFAULT_SCAN_IGNORED_DIRECTORIES,
) -> Iterator[Path]:
    """Walk regular case entries without following nested symbolic links.

    ``root`` has already passed ``PathPolicy`` and may itself resolve to a registered external
    evidence source. Nested links are intentionally excluded so a broad scan cannot silently
    expand beyond that explicitly registered root.
    """
    if root.is_file():
        if not root.is_symlink():
            yield root
        return
    if not root.is_dir():
        return
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_directories = [
            name
            for name in sorted(directories)
            if name not in ignored_directories and not (current_path / name).is_symlink()
        ]
        directories[:] = safe_directories
        if include_directories:
            yield from (current_path / name for name in safe_directories)
        for name in sorted(files):
            candidate = current_path / name
            if not candidate.is_symlink():
                yield candidate


class PathPolicy:
    """Resolve paths without allowing unregistered case-boundary escapes."""

    def __init__(self, case_root: Path, evidence_sources: dict[str, str] | None = None):
        self.case_root = case_root.resolve()
        self.evidence_sources = evidence_sources or {}

    def resolve_read(self, requested: str) -> Path:
        if "\x00" in requested:
            raise SecurityError("The requested path contains a null byte.")
        raw = Path(requested)
        if raw.is_absolute():
            raise SecurityError("Use a path relative to the current case.")
        lexical = Path(os.path.abspath(self.case_root / raw))
        if not is_relative_to(lexical, self.case_root):
            raise SecurityError("The requested file is outside the current case.")
        resolved = lexical.resolve(strict=True)
        if is_relative_to(resolved, self.case_root):
            return resolved
        for case_path, source_path in self.evidence_sources.items():
            evidence_root = (self.case_root / case_path).absolute()
            if lexical == evidence_root or is_relative_to(lexical, evidence_root):
                suffix = lexical.relative_to(evidence_root)
                expected = (expand_path(source_path) / suffix).resolve(strict=True)
                if resolved == expected:
                    return resolved
        raise SecurityError("The symbolic link target is not registered evidence.")

    def resolve_write(self, requested: str) -> Path:
        if "\x00" in requested:
            raise SecurityError("The requested path contains a null byte.")
        raw = Path(requested)
        if raw.is_absolute():
            raise SecurityError("Use a path relative to the current case.")
        candidate = Path(os.path.abspath(self.case_root / raw))
        if not is_relative_to(candidate, self.case_root):
            raise SecurityError("The requested output path is outside the current case.")
        parent = candidate.parent.resolve(strict=True)
        if not is_relative_to(parent, self.case_root):
            raise SecurityError("The requested output parent escapes through a symbolic link.")
        return candidate
