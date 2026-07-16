"""Safe evidence registration without modifying source artifacts."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from maldroid.case_manager import Case, CaseManager
from maldroid.exceptions import CaseError
from maldroid.models import EvidenceRecord
from maldroid.paths import expand_path


class EvidenceManager:
    def __init__(self, case_manager: CaseManager):
        self.case_manager = case_manager

    def register(
        self,
        case: Case,
        source: Path,
        mode: Literal["symlink", "copy"] = "symlink",
        calculate_hash: bool = False,
    ) -> EvidenceRecord:
        source_path = expand_path(source)
        if not source_path.exists():
            raise CaseError(f"Evidence source does not exist: {source_path}")
        if mode not in {"symlink", "copy"}:
            raise CaseError("Evidence mode must be symlink or copy.")
        evidence_directory = case.root / "evidence"
        evidence_directory.mkdir(parents=True, exist_ok=True)
        destination = _unique_destination(evidence_directory / source_path.name)
        record: EvidenceRecord | None = None
        try:
            if mode == "symlink":
                destination.symlink_to(
                    source_path.resolve(), target_is_directory=source_path.is_dir()
                )
            elif source_path.is_dir():
                shutil.copytree(source_path, destination, symlinks=True)
            else:
                shutil.copy2(source_path, destination)
            stat = source_path.stat()
            record = EvidenceRecord(
                id=f"EVID-{uuid.uuid4().hex[:8].upper()}",
                case_path=destination.relative_to(case.root).as_posix(),
                source_path=str(source_path),
                source_resolved_path=str(source_path.resolve()),
                mode=mode,
                size=_path_size(source_path),
                modified_at=datetime.fromtimestamp(stat.st_mtime)
                .astimezone()
                .isoformat(timespec="seconds"),
                sha256=_sha256(source_path) if calculate_hash and source_path.is_file() else None,
            )
            case.state.evidence.append(record)
            self.case_manager.save(case)
            return record
        except Exception:
            if record is not None and record in case.state.evidence:
                case.state.evidence.remove(record)
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination, ignore_errors=True)
            else:
                destination.unlink(missing_ok=True)
            raise


def _unique_destination(path: Path) -> Path:
    candidate = path
    counter = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        counter += 1
    return candidate


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        directories[:] = [name for name in directories if not (root_path / name).is_symlink()]
        for name in files:
            candidate = root_path / name
            if candidate.is_symlink():
                continue
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
    return total


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
