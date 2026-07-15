"""Case creation, initialization, discovery, and persistent state."""

from __future__ import annotations

import json
import re
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from maldroid.config import AppConfig, resolved_cases_directory
from maldroid.constants import STATE_SCHEMA_VERSION
from maldroid.exceptions import CaseError
from maldroid.io_utils import atomic_write_json, atomic_write_text
from maldroid.models import CaseMetadata, CaseState, now_iso
from maldroid.paths import data_directory, expand_path


@dataclass
class Case:
    root: Path
    metadata: CaseMetadata
    state: CaseState

    @property
    def internal(self) -> Path:
        return self.root / ".maldroid"


class CaseManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.registry_path = data_directory() / "cases.json"

    def create(self, name: str | None = None) -> Case:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        suffix = f"-{_slug(name)}" if name else ""
        base = resolved_cases_directory(self.config)
        root = _unique_directory(base / f"{timestamp}{suffix}")
        root.mkdir(parents=True)
        for child in ("evidence", "workspace", "tool-output", "notes", "reports"):
            (root / child).mkdir()
        for child in ("sessions", "indexes", "cache", "knowledge", "logs"):
            (root / ".maldroid" / child).mkdir(parents=True, exist_ok=True)
        (root / "notes" / "CASE.md").write_text("# Case Notes\n\n", encoding="utf-8")
        (root / "notes" / "FINDINGS.md").write_text("# Findings\n\n", encoding="utf-8")
        (root / "notes" / "TODO.md").write_text("# TODO\n\n", encoding="utf-8")
        (root / "notes" / "CHECKPOINTS.md").write_text(
            "# Research Checkpoints\n\n", encoding="utf-8"
        )
        (root / "notes" / "SESSION_SUMMARY.md").write_text(
            "# Session Summary\n\n", encoding="utf-8"
        )
        return self._initialize(root, managed=True, name=name or root.name)

    def initialize_existing(self, directory: Path, name: str | None = None) -> Case:
        root = expand_path(directory)
        if not root.is_dir():
            raise CaseError(f"The case directory does not exist: {root}")
        if (root / ".maldroid" / "case.toml").exists():
            return self.open(root)
        (root / ".maldroid").mkdir(exist_ok=True)
        return self._initialize(root, managed=False, name=name or root.name)

    def _initialize(self, root: Path, managed: bool, name: str) -> Case:
        metadata = CaseMetadata(
            case_id=str(uuid.uuid4()),
            name=name,
            root=str(root.resolve()),
            managed=managed,
        )
        state = CaseState(
            active_profile=self.config.general.default_profile,
            context_size=self.config.general.default_context_size,
            model_path=self.config.llama.model,
        )
        case = Case(root=root.resolve(), metadata=metadata, state=state)
        self.save(case)
        self._update_registry(case)
        return case

    def open(self, directory: Path) -> Case:
        root = expand_path(directory).resolve()
        metadata_path = root / ".maldroid" / "case.toml"
        state_path = root / ".maldroid" / "state.json"
        if not metadata_path.is_file() or not state_path.is_file():
            raise CaseError(f"Not a MalDroid case: {root}")
        try:
            with metadata_path.open("rb") as handle:
                metadata = CaseMetadata.model_validate(tomllib.load(handle))
            state = CaseState.model_validate(
                _migrate_state(json.loads(state_path.read_text(encoding="utf-8")))
            )
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            raise CaseError(f"Cannot load case metadata from {root}: {exc}") from exc
        if Path(metadata.root).resolve() != root:
            metadata.root = str(root)
        metadata.last_opened_at = now_iso()
        case = Case(root=root, metadata=metadata, state=state)
        self.save(case)
        self._update_registry(case)
        return case

    def save(self, case: Case) -> None:
        case.internal.mkdir(parents=True, exist_ok=True)
        metadata = case.metadata
        toml = (
            f"schema_version = {metadata.schema_version}\n"
            f"case_id = {json.dumps(metadata.case_id)}\n"
            f"name = {json.dumps(metadata.name, ensure_ascii=False)}\n"
            f"root = {json.dumps(metadata.root, ensure_ascii=False)}\n"
            f"managed = {str(metadata.managed).lower()}\n"
            f"created_at = {json.dumps(metadata.created_at)}\n"
            f"last_opened_at = {json.dumps(metadata.last_opened_at)}\n"
        )
        atomic_write_text(case.internal / "case.toml", toml)
        atomic_write_json(case.internal / "state.json", case.state.model_dump(mode="json"))

    def resume(self) -> Case:
        records = self._read_registry()
        existing = [record for record in records if Path(record["path"]).is_dir()]
        if not existing:
            raise CaseError("No previous MalDroid case was found.")
        latest = max(existing, key=lambda item: item["last_opened_at"])
        return self.open(Path(latest["path"]))

    def list_cases(self) -> list[dict[str, object]]:
        records = self._read_registry()
        output: list[dict[str, object]] = []
        for record in sorted(records, key=lambda item: item["last_opened_at"], reverse=True):
            root = Path(record["path"])
            if not root.exists():
                continue
            try:
                case = self._load_without_touch(root)
                output.append(
                    {
                        **record,
                        "profile": case.state.active_profile,
                        "findings": len(case.state.findings),
                        "open_todos": sum(item.status == "open" for item in case.state.todos),
                    }
                )
            except CaseError:
                continue
        return output

    def _load_without_touch(self, root: Path) -> Case:
        try:
            with (root / ".maldroid" / "case.toml").open("rb") as handle:
                metadata = CaseMetadata.model_validate(tomllib.load(handle))
            state = CaseState.model_validate(
                _migrate_state(
                    json.loads((root / ".maldroid" / "state.json").read_text(encoding="utf-8"))
                )
            )
            return Case(root=root, metadata=metadata, state=state)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            raise CaseError(str(exc)) from exc

    def _read_registry(self) -> list[dict[str, str]]:
        if not self.registry_path.exists():
            return []
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return [item for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            return []

    def _update_registry(self, case: Case) -> None:
        records = [
            item for item in self._read_registry() if item.get("case_id") != case.metadata.case_id
        ]
        records.append(
            {
                "case_id": case.metadata.case_id,
                "name": case.metadata.name,
                "path": str(case.root),
                "created_at": case.metadata.created_at,
                "last_opened_at": case.metadata.last_opened_at,
            }
        )
        atomic_write_json(self.registry_path, records)


def _slug(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-.")
    return cleaned[:64] or "case"


def _unique_directory(path: Path) -> Path:
    candidate = path
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}-{counter}")
        counter += 1
    return candidate


def _migrate_state(payload: object) -> dict[str, object]:
    """Apply small forward-only migrations while preserving existing case content."""
    if not isinstance(payload, dict):
        raise ValueError("case state must be a JSON object")
    migrated = dict(payload)
    version = int(migrated.get("schema_version", 1))
    if version > STATE_SCHEMA_VERSION:
        raise ValueError(
            f"case state schema {version} is newer than supported schema {STATE_SCHEMA_VERSION}"
        )
    if version < 2:
        migrated.setdefault("checkpoints", [])
        notes = migrated.get("notes", [])
        if isinstance(notes, list):
            migrated["notes"] = [
                {**note, "kind": "research_note"}
                if isinstance(note, dict) and "kind" not in note
                else note
                for note in notes
            ]
        migrated["schema_version"] = 2
    return migrated
