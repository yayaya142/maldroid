from __future__ import annotations

from pathlib import Path

import pytest

from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.evidence_manager import EvidenceManager
from maldroid.exceptions import SecurityError
from maldroid.paths import PathPolicy


def test_managed_case_creation_and_resume(app_config: AppConfig) -> None:
    manager = CaseManager(app_config)
    case = manager.create("Example")
    assert case.metadata.managed is True
    assert (case.root / ".maldroid" / "case.toml").is_file()
    assert (case.root / "notes" / "FINDINGS.md").is_file()
    resumed = manager.resume()
    assert resumed.metadata.case_id == case.metadata.case_id
    assert manager.list_cases()[0]["findings"] == 0


def test_existing_directory_is_initialized_minimally(tmp_path: Path, app_config: AppConfig) -> None:
    existing = tmp_path / "researcher"
    existing.mkdir()
    (existing / "artifact.txt").write_text("content", encoding="utf-8")
    case = CaseManager(app_config).initialize_existing(existing)
    assert case.metadata.managed is False
    assert (existing / ".maldroid").is_dir()
    assert not (existing / "evidence").exists()


def test_evidence_symlink_copy_duplicates_and_hash(tmp_path: Path, app_config: AppConfig) -> None:
    source = tmp_path / "bundle.js"
    source.write_text("hello evidence", encoding="utf-8")
    manager = CaseManager(app_config)
    case = manager.create()
    evidence = EvidenceManager(manager)
    linked = evidence.register(case, source, "symlink", calculate_hash=True)
    copied = evidence.register(case, source, "copy")
    assert (case.root / linked.case_path).is_symlink()
    assert (case.root / copied.case_path).is_file()
    assert linked.case_path != copied.case_path
    assert linked.sha256 is not None
    assert source.read_text(encoding="utf-8") == "hello evidence"


def test_registered_directory_symlink_allows_nested_reads(
    tmp_path: Path, app_config: AppConfig
) -> None:
    source = tmp_path / "external"
    source.mkdir()
    (source / "nested.txt").write_text("safe", encoding="utf-8")
    manager = CaseManager(app_config)
    case = manager.create()
    record = EvidenceManager(manager).register(case, source, "symlink")
    policy = PathPolicy(case.root, {record.case_path: record.source_resolved_path})
    resolved = policy.resolve_read(record.case_path + "/nested.txt")
    assert resolved == (source / "nested.txt").resolve()
    with pytest.raises(SecurityError):
        policy.resolve_read("../outside")


def test_registered_symlink_target_swap_is_rejected(tmp_path: Path, app_config: AppConfig) -> None:
    original = tmp_path / "original.txt"
    replacement = tmp_path / "replacement.txt"
    original.write_text("original", encoding="utf-8")
    replacement.write_text("replacement", encoding="utf-8")
    manager = CaseManager(app_config)
    case = manager.create()
    record = EvidenceManager(manager).register(case, original, "symlink")
    link = case.root / record.case_path
    link.unlink()
    link.symlink_to(replacement)
    policy = PathPolicy(case.root, {record.case_path: record.source_resolved_path})
    with pytest.raises(SecurityError, match="not registered"):
        policy.resolve_read(record.case_path)
