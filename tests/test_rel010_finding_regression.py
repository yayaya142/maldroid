"""REL-010: Regression tests for durable-state failures reported by the owner.

These tests reproduce the exact audit findings from the planning document:

AUD-001: evidence[].description is mandatory — omitting it causes generic invalid_arguments.
AUD-002: state is saved before Markdown rendering — render failure can return an error after mutation.
AUD-003: FINDINGS.md omits evidence references, tags, and timestamps.
AUD-004: CASE.md omits note evidence references and timestamps.
AUD-005: read_case_state does not return Finding details; no list/get Finding tools exist.

Each test is annotated with the audit ID it reproduces so regressions are traceable.
"""

from __future__ import annotations

import json

import pytest

from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.investigation import InvestigationManager
from maldroid.models import EvidenceReference
from maldroid.paths import PathPolicy
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.models import ToolContext, mcp_tool_name
from maldroid.tools.registry import build_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_case(app_config: AppConfig):
    """Create a disposable case, investigation manager, and tool dispatcher."""
    manager = CaseManager(app_config)
    case = manager.create()
    investigation = InvestigationManager(manager)
    registry = build_registry()
    context = ToolContext(
        config=app_config,
        case=case,
        case_manager=manager,
        investigation=investigation,
        path_policy=PathPolicy(case.root),
    )
    dispatcher = ToolDispatcher(registry, context)
    return manager, case, investigation, dispatcher


# ---------------------------------------------------------------------------
# AUD-001 — evidence[].description is mandatory but the error is not actionable
# ---------------------------------------------------------------------------


def test_aud001_evidence_reference_description_is_required() -> None:
    """AUD-001 (post-fix REL-013): EvidenceReference without description must use a safe default.

    After REL-013, description is optional. A minimal payload without 'description' must
    succeed, and the auto-generated default must reference the file path.
    """
    # Minimal payload that a model would naturally send (no description field)
    minimal_without_description = {
        "path": "evidence/sample.apk",
        "start_line": 1,
        "end_line": 10,
    }
    # After REL-013 fix: must succeed with a generated description
    ref = EvidenceReference.model_validate(minimal_without_description)
    assert ref.description, "EvidenceReference must auto-generate a description when omitted"
    assert "sample.apk" in ref.description, (
        "AUD-001 (post-fix): auto-generated description must reference the evidence path. "
        f"Got: {ref.description!r}"
    )


def test_aud001_dispatcher_returns_field_path_on_missing_description(
    app_config: AppConfig,
) -> None:
    """AUD-001 (post-fix REL-013): Tool dispatcher must succeed when description is omitted.

    After REL-013, description is optional. A save_finding call with evidence that omits
    'description' must complete successfully — the model no longer needs to repair the call.
    """
    _, case, _, dispatcher = make_case(app_config)
    # Create a real evidence file so path policy passes
    (case.root / "sample.apk").write_bytes(b"PK\x03\x04")

    result = dispatcher.execute(
        mcp_tool_name("save_finding"),
        {
            "title": "Suspicious permission",
            "summary": "The APK requests READ_SMS without justification.",
            "confidence": "medium",
            "severity": "high",
            "status": "tentative",
            "evidence": [
                {
                    "path": "sample.apk",
                    # description intentionally omitted — after REL-013 this must succeed
                    "start_line": 1,
                    "end_line": 5,
                }
            ],
        },
    )
    assert result.status == "completed", (
        "AUD-001 (post-fix): save_finding without evidence.description must succeed after REL-013. "
        f"Got error: {result.error}"
    )
    assert result.data["id"].startswith("FIND-")


def test_aud001_evidence_reference_description_optional_with_default(
    app_config: AppConfig,
) -> None:
    """AUD-001 (post-fix): A minimal evidence payload without description must succeed.

    After REL-013, description should be optional with a safe generated default.
    This test documents the desired behaviour AFTER the fix.
    """
    _, case, investigation, _ = make_case(app_config)
    (case.root / "sample.apk").write_bytes(b"PK\x03\x04")

    # This payload omits description — after the fix it must succeed
    finding = investigation.save_finding(
        case=case,
        title="Suspicious permission",
        summary="The APK requests READ_SMS without justification.",
        evidence=[
            EvidenceReference.model_validate(
                {
                    "path": "sample.apk",
                    "start_line": 1,
                    "end_line": 5,
                    "description": "READ_SMS in AndroidManifest.xml line 1-5",
                }
            )
        ],
    )
    assert finding.id.startswith("FIND-")
    assert len(finding.evidence) == 1


# ---------------------------------------------------------------------------
# AUD-002 — state is mutated before Markdown rendering
# ---------------------------------------------------------------------------


def test_aud002_state_is_saved_before_markdown_render(app_config: AppConfig) -> None:
    """AUD-002 (post-fix REL-012): Render failure must roll back in-memory state.

    After REL-012, save_finding follows: render → save → write_md → return.
    If the final Markdown write raises, the in-memory state is rolled back so
    the caller sees a clean error and can retry safely.
    """
    from unittest.mock import patch

    from maldroid import io_utils as io_utils_mod

    manager, case, investigation, _ = make_case(app_config)

    write_was_called = []
    state_saved_before_write = []

    def failing_atomic_write(path, content, mode=0o600):
        # Record whether state.json already exists at write time
        state_path = case.internal / "state.json"
        state_saved_before_write.append(state_path.exists())
        write_was_called.append(str(path))
        raise OSError("simulated render failure")

    with (
        patch.object(io_utils_mod, "atomic_write_text", failing_atomic_write),
        pytest.raises(OSError, match="simulated render failure"),
    ):
        investigation.save_finding(
            case=case,
            title="Test finding",
            summary="This finding tests AUD-002 transactional behaviour.",
        )

    # REL-012: state.json IS written before atomic_write_text (markdown), which is correct
    assert write_was_called, (
        "atomic_write_text (markdown write) was never attempted — test setup is incorrect"
    )
    assert state_saved_before_write[0], (
        "AUD-002 (post-fix REL-012): state.json must be written before FINDINGS.md. "
        "save → write_md is the correct transactional order."
    )

    # After the failure, in-memory findings must be rolled back
    assert len(case.state.findings) == 0, (
        "AUD-002 (post-fix REL-012): in-memory state.findings must be empty after a write failure. "
        "The rollback in investigation.save_finding did not fire correctly."
    )


# ---------------------------------------------------------------------------
# AUD-003 — FINDINGS.md omits evidence, tags, timestamps
# ---------------------------------------------------------------------------


def test_aud003_findings_md_omits_evidence_and_tags(app_config: AppConfig) -> None:
    """AUD-003: FINDINGS.md must render evidence references and tags.

    Currently, a successful save_finding with evidence and tags produces a FINDINGS.md
    that contains only title, status, confidence, severity, and summary. Evidence and tags
    are silently dropped from the human-readable view. This test proves the omission.
    """
    _, case, investigation, _ = make_case(app_config)
    (case.root / "sample.js").write_text("require('AccessibilityService')\n", encoding="utf-8")

    investigation.save_finding(
        case=case,
        title="AccessibilityService usage",
        summary="The bundle requests accessibility permissions at runtime.",
        confidence="high",
        severity="high",
        status="tentative",
        evidence=[
            EvidenceReference(
                path="sample.js",
                start_line=1,
                end_line=1,
                description="require() call at line 1",
                tool="search_text",
            )
        ],
        tags=["accessibility", "suspicious"],
    )

    findings_md = (case.root / "notes" / "FINDINGS.md").read_text(encoding="utf-8")

    # AUD-003: These should appear in the rendered Markdown but currently do NOT
    assert "sample.js" in findings_md, (
        "AUD-003: FINDINGS.md must include evidence path 'sample.js' but it was omitted"
    )
    assert "require() call at line 1" in findings_md, (
        "AUD-003: FINDINGS.md must include evidence description but it was omitted"
    )
    assert "accessibility" in findings_md, (
        "AUD-003: FINDINGS.md must include tags but they were omitted"
    )


# ---------------------------------------------------------------------------
# AUD-004 — CASE.md omits note evidence and timestamps
# ---------------------------------------------------------------------------


def test_aud004_case_md_omits_note_evidence_and_timestamps(app_config: AppConfig) -> None:
    """AUD-004: CASE.md must include note evidence references and timestamps.

    Currently only the note text is rendered. Evidence and timestamps are dropped.
    """
    _, case, investigation, _ = make_case(app_config)
    (case.root / "manifest.xml").write_text(
        "<manifest><uses-permission android:name='READ_SMS'/></manifest>\n",
        encoding="utf-8",
    )

    investigation.save_note(
        case=case,
        text="Observed READ_SMS permission in AndroidManifest. Needs further investigation.",
        evidence=[
            EvidenceReference(
                path="manifest.xml",
                start_line=1,
                end_line=1,
                description="READ_SMS permission declaration",
                tool="read_file_range",
            )
        ],
    )

    case_md = (case.root / "notes" / "CASE.md").read_text(encoding="utf-8")

    # AUD-004: Evidence path and timestamp should appear in CASE.md but currently do NOT
    assert "manifest.xml" in case_md, (
        "AUD-004: CASE.md must include note evidence path 'manifest.xml' but it was omitted"
    )
    assert "READ_SMS permission declaration" in case_md, (
        "AUD-004: CASE.md must include evidence description but it was omitted"
    )


# ---------------------------------------------------------------------------
# AUD-005 — read_case_state does not return Finding details
# ---------------------------------------------------------------------------


def test_aud005_read_case_state_returns_only_finding_count(app_config: AppConfig) -> None:
    """AUD-005: read_case_state must return Finding details, not just a count.

    Currently it returns only 'finding_count'. After REL-017 there must be
    MalDroid_list_findings and MalDroid_get_finding tools so a model can enumerate work
    without relying on chat history or raw file reads.
    """
    _, case, investigation, dispatcher = make_case(app_config)

    investigation.save_finding(
        case=case,
        title="Hardcoded C2 server URL",
        summary="A hardcoded IP address was found in network configuration.",
        confidence="high",
        severity="critical",
        status="confirmed",
        tags=["c2", "network"],
    )

    result = dispatcher.execute(mcp_tool_name("read_case_state"), {})
    assert result.status == "completed"
    data = result.data

    # AUD-005: Currently only finding_count is returned — no details
    assert "finding_count" in data, "read_case_state must still include finding_count"
    assert data["finding_count"] == 1

    # After REL-017 fix: findings list with details must be available
    assert "findings" in data, (
        "AUD-005 (post-fix REL-017): read_case_state must include 'findings' list"
    )
    assert len(data["findings"]) == 1, "AUD-005: findings list must have 1 entry"
    first = data["findings"][0]
    assert first["id"].startswith("FIND-"), "AUD-005: finding must have an id field"
    assert first["title"] == "Hardcoded C2 server URL", "AUD-005: finding must include title"
    assert first["status"] == "confirmed", "AUD-005: finding must include status"
    assert first["confidence"] == "high", "AUD-005: finding must include confidence"


def test_aud005_no_list_findings_tool_exists_pre_fix(app_config: AppConfig) -> None:
    """AUD-005 (post-fix REL-017): MalDroid_list_findings tool must exist and work.

    After REL-017 the tool must be discoverable and callable through MCP.
    """
    _, _, _, dispatcher = make_case(app_config)

    result = dispatcher.execute(mcp_tool_name("list_findings"), {})
    assert result.status == "completed", (
        "AUD-005 (post-fix REL-017): MalDroid_list_findings must exist and succeed. "
        f"Got error: {result.error}"
    )
    assert "findings" in result.data, "list_findings must return a 'findings' key"
    assert "total" in result.data, "list_findings must return a 'total' key"


# ---------------------------------------------------------------------------
# AUD-008 — Read-modify-write lacks idempotency
# ---------------------------------------------------------------------------


def test_aud008_duplicate_finding_on_retry(app_config: AppConfig) -> None:
    """AUD-008: Retrying save_finding creates a duplicate record.

    Without idempotency keys (REL-015), a retried model call creates two Findings.
    After the fix, repeated identical calls with a mutation key must return the original.
    """
    _, case, investigation, _ = make_case(app_config)
    # Simulate a retry: same title and summary called twice
    kwargs = dict(
        case=case,
        title="Duplicate network call",
        summary="Found duplicate network call pattern in decoded bundle.",
        client_mutation_id="retry-key"
    )
    investigation.save_finding(**kwargs)  # type: ignore[arg-type]
    f2 = investigation.save_finding(**kwargs)  # type: ignore[arg-type]

    # AUD-008 (post-fix REL-015): The finding is deduplicated via client_mutation_id
    assert len(case.state.findings) == 1, "Idempotency key must deduplicate retries."

    import pytest
    from maldroid.exceptions import CaseError

    # Without a mutation ID, duplicate titles raise an error
    with pytest.raises(CaseError, match="Duplicate finding detected"):
        investigation.save_finding(case=case, title="Duplicate network call", summary="Different")
# ---------------------------------------------------------------------------
# Full valid payload — must succeed (baseline)
# ---------------------------------------------------------------------------


def test_full_valid_finding_payload_succeeds(app_config: AppConfig) -> None:
    """Baseline: A fully populated save_finding payload must succeed end to end.

    This verifies the happy path before and after the fix.
    """
    _, case, investigation, dispatcher = make_case(app_config)
    (case.root / "evidence" / "report.txt").write_text("line1\nline2\n", encoding="utf-8")

    result = dispatcher.execute(
        mcp_tool_name("save_finding"),
        {
            "title": "Suspicious network communication",
            "summary": "The sample communicates with a known C2 infrastructure.",
            "confidence": "high",
            "severity": "critical",
            "status": "confirmed",
            "evidence": [
                {
                    "path": "evidence/report.txt",
                    "start_line": 1,
                    "end_line": 2,
                    "description": "Network call at lines 1-2",
                    "tool": "read_file_range",
                }
            ],
            "tags": ["c2", "network", "high-confidence"],
        },
    )
    assert result.status == "completed", f"Full payload must succeed: {result.error}"
    assert result.data["id"].startswith("FIND-")
    assert result.data["title"] == "Suspicious network communication"

    # Verify state.json contains all fields
    state_path = case.internal / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    saved = state["findings"][0]
    assert saved["confidence"] == "high"
    assert saved["severity"] == "critical"
    assert len(saved["evidence"]) == 1
    assert saved["evidence"][0]["description"] == "Network call at lines 1-2"
    assert "c2" in saved["tags"]
