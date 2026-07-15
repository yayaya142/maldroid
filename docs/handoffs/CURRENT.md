# Current Handoff

Task: `PLATFORM-010`
Next task: `PLATFORM-011`

## Outcome

The owner reprioritized MalDroid around real multi-hour research usability. The local implementation
now provides semantic research memory, bounded long-run context, a faster interactive research CLI,
deep React Native and Native/Ghidra guidance, and focused large-evidence tools.

## Implemented state and memory

- State schema v2 adds typed `InvestigationCheckpoint` records with objective, completed work,
  evidence learned, changed Finding/TODO IDs, unresolved questions, uncertainty, status, phase, and
  next action. Existing v1 cases migrate on open without losing Notes.
- Automatic continuity uses `MalDroid_save_checkpoint`; it never stores tool names, arguments,
  result dumps, or failures. Low-value fallback content is skipped.
- Model Notes are restricted to research insights, decisions, and hypotheses. Operational content
  is rejected and stays in session/tool audit. Direct human `/note` remains free-form `user_note`.
- Complete paginated list/get MCP readback exists for Findings, Notes, TODOs, and Checkpoints.
- `MalDroid_build_research_report` atomically rebuilds `reports/RESEARCH_REPORT.md` from durable
  Findings, TODOs, and latest continuity.

## Context and controller

- The next completion budget is reserved in context-pressure calculations.
- `limits.retained_tool_results` defaults to six. Older tool results become small working-context
  receipts; their full JSONL/output remains on disk. Old reasoning blocks are also dropped from the
  active request only.
- The original objective is no longer repeated at every autonomous tool window and is restored only
  when actual compaction resets the conversation.
- React Native and Native profiles automatically load one bounded methodology playbook at activation.
- Internal subagent orchestration is deliberately deferred until typed memory and context retention
  pass real multi-hour acceptance; no extra model/state-merging boundary was introduced.

## CLI and tools

- Added `/dashboard`, `/inventory`, `/indicators`, `/triage`, `/findings ID`, `/timeline [COUNT]`,
  and `/report`. Toolbar/status/checkpoint views now display semantic continuity.
- New core tools: artifact inventory, network-indicator extraction, multi-family behavior search,
  bounded byte-range hex/ASCII reads, and deterministic report generation.
- Behavior-family search prefers ripgrep and falls back to a bounded streaming Python scanner on
  hosts such as the macOS CI image where ripgrep is not installed.
- New React Native tools: behavior-family triage mapped to Metro modules/offsets and bridge inventory.
- New Native tools: ELF dependencies, relocations, JNI surface, and hardening indicators.
- Added deep automatically routed playbooks for React Native data-flow research and Native ELF/JNI/
  Ghidra MCP workflows.

## Persistence and security

- Managed investigation remains static-only. No evidence execution, network access, uploads, shell,
  dynamic analysis, ADB, Frida, or emulator capability was added.
- All new tools use central path policy, bounded inputs/results, local output, argument arrays, and
  `shell=False`. Ghidra remains an independent external MCP authority.
- ADR-0012 records the semantic-memory, context-retention, guide-routing, and subagent-deferral
  decisions. `SECURITY.md` now matches the accepted owner-controlled WebUI host-tool boundary.

## Verification

Startup baseline:

```text
./scripts/dev doctor
```

Result: Python/platform/ripgrep and loopback boundaries passed. This Linux workspace does not have
the configured macOS GGUF or `llama-server`; real-model checks remain environment-gated.

Focused and full tests:

```text
./scripts/dev test tests/test_cases_evidence.py tests/test_tools_agent.py tests/test_mcp_server.py
./scripts/dev test tests/test_large_react_native.py tests/test_framework_profiles.py tests/test_triage_tools.py
./scripts/dev test tests/test_ui.py tests/test_triage_tools.py
./scripts/dev test
```

Results: all focused suites passed; full suite passed with `106 passed`.

Release gate:

```text
./scripts/dev release-check
```

The final run passed Ruff formatting/lint, mypy for 37 source files, 106 tests with 72% coverage,
project hygiene, installer dry-run, wheel build, and archive verification. The wheel is
`dist/maldroid-0.1.0-py3-none-any.whl` (121,025 bytes after the macOS fallback fix).

GitHub Actions run `29430555735` passed Kali and exposed one macOS-only failure: the new behavior
search required ripgrep, which the macOS image does not install. The focused follow-up adds and
tests the bounded streaming fallback. A replacement CI run is required after the follow-up commit.

## Known limitations

- No real Gemma 4, llama-server, macOS Terminal, or Ghidra MCP long-run acceptance occurred in this
  Linux workspace.
- Canonical state still lacks revision/idempotency/multiprocess transaction semantics from
  `REL-011..020`; schema v2 preserves the existing rollback model.
- Automatic semantic fallback cannot manufacture research meaning. When the model supplies no
  semantic synthesis and no durable Finding/TODO exists, MalDroid skips the checkpoint.
- URL/behavior pattern hits are triage leads, not reachability or maliciousness conclusions.
- React Native Metro parsing remains heuristic and Hermes compatibility remains version-sensitive.
- Internal subagents are not implemented.

## Next command

```bash
git diff --check && git status --short
```

Commit the macOS fallback as `PLATFORM-010 add portable behavior search fallback`, push `main`, and
wait for both CI jobs. Then install the resulting commit on the owner's macOS host for
`PLATFORM-011`.
