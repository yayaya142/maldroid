# MalDroid Reliability and Research Platform Master Plan

Status: active gated backlog; `PLATFORM-010`, `PLATFORM-012`, `PLATFORM-013`, `PLATFORM-014`, and `PLATFORM-015` are implemented locally
Owner priority: make MalDroid a trustworthy daily research CLI before expanding breadth  
Execution model: one agent and one task ID at a time  
Canonical original requirements: `Tasks.MD` (read-only)

## 0. Owner reprioritization implemented on 2026-07-15, 2026-07-16, and 2026-07-24

The owner explicitly reprioritized broad long-investigation usability ahead of the original
one-item reliability chain. `PLATFORM-010` implemented a coherent first slice across the existing
gates: state schema v2 typed Checkpoints, separation and quality enforcement for Notes, paginated
state readback, deterministic reports, working-context receipts/reservation, interactive research
commands, deep React Native and Native/Ghidra methodologies, automatic guide routing, and focused
large-evidence/profile tools.

This does not close the remaining transaction/revision/idempotency work in `REL-011..020`, and it
does not claim physical-host acceptance. `PLATFORM-011` is the next real-model acceptance gate.
Internal subagent orchestration was considered and deliberately deferred until typed state and
long-run context behavior are verified on the owner's cases.

On 2026-07-16 the owner reprioritized Web 100%-zoom fit and real local-model responsiveness.
`PLATFORM-012` narrowed and balanced desktop content, then removed compounded turn latency from
repeated profile scans, nested retries, forced checkpoint generations, post-answer Web compaction,
and retained completed-turn thoughts. It also added llama.cpp prompt/cache/first-token telemetry and
one history-safe empty-response recovery. This is locally tested but does not replace the physical
Gemma 4/macOS acceptance in `PLATFORM-011`.

`PLATFORM-013` then performed the owner-requested full regression run. It added an identical
tool/result warning-and-stop guard, generation-free deterministic shutdown summaries, safe
non-following traversal and globally bounded large-repository searches/artifacts, transactional
evidence/path-policy refresh, authoritative Web reconnect and concurrency handling, bounded history
views, a Settings **Stop model** action, and extensive regression fixtures. This closes the
unchanged-static-tool loop slice of `AGENT-013`; adaptive planning beyond that guard remains future
work. Physical model, macOS, and Ghidra acceptance still belongs to `PLATFORM-011`.

On 2026-07-24 the owner put Web feature work on hold and reprioritized daily CLI latency plus a
much broader static-research toolset. `PLATFORM-014` adds CLI `fast`/`balanced`/`deep` presets and a
dynamic authoritative tool catalog so the new capabilities do not inflate every local-model
request. It adds twelve bounded file/source/archive/structured/SQLite/manifest/source-map tools,
fixes implicit new cases remaining manually locked to Generic, makes CLI the recommended selector
choice, and labels Web BETA. This is an explicit exception to the earlier broad-tool ordering; it
does not close the remaining reliability tasks or physical `PLATFORM-011` acceptance.

Later on 2026-07-24 the owner explicitly reprioritized efficient whole-code/obfuscation analysis
and Python decoder authoring without execution. `PLATFORM-015` captures large fenced source outside
model/session history, adds a contentless code index, focused symbol context, obfuscation triage,
and provenance-rich bounded transform chains. ADR 0020 accepts restricted transforms plus
append-only, risk-scanned, review-only Python artifacts; MalDroid exposes no script execution tool
and makes no sandbox claim. This is another owner-authorized ordering exception and does not close
physical acceptance or the durable-state chain.

## 1. Instructions for the next agent

This document is the active rebuild program requested by the project owner. Do not attempt to
implement the entire program in one change. Start with `REL-010`, complete its tests and handoff,
then take the next dependency-ready task. Reliability gates block feature gates.

The owner explicitly reported these user-visible failures:

1. `MalDroid_save_finding` often appears not to work.
2. Notes, Findings, TODOs, and other durable state are not reliably or meaningfully maintained.
3. Automatic notes frequently contain errors, tool names, and noise instead of research progress.
4. The model lacks enough investigation methodology and capable static-analysis tools.
5. `maldroid cases` should open the cases directory in Finder/the system file manager.
6. The CLI needs substantially better usability and transparency.
7. The agent needs an explicitly designed way to write and execute Python decoding scripts.

Do not dismiss a field report because synthetic tests pass. Capture the real failing payload,
session event, MCP response, state file, and rendered Markdown before deciding on a fix.

## 2. Evidence from the planning audit

The following are observed facts in commit `f900a92`, not hypothetical defects:

| ID | Severity | Observation | Consequence |
|---|---:|---|---|
| AUD-001 | Critical | `save_finding` accepts a fully populated payload, but `EvidenceReference.description` is mandatory. A realistic payload containing path and line range without description returns generic `invalid_arguments`. | Gemma can repeatedly fail to save a valid conclusion without knowing the precise correction. |
| AUD-002 | High | `InvestigationManager` mutates `case.state`, writes `state.json`, and only then renders/appends Markdown. | A Markdown failure can return a tool error after canonical state already changed; a retry can duplicate data. |
| AUD-003 | High | `FINDINGS.md` renders title, status, confidence, severity, and summary only. It omits evidence references, tags, timestamps, and tool provenance. | A successful Finding appears incomplete or missing its most important proof. |
| AUD-004 | High | `CASE.md` renders note text only and omits note evidence references and timestamps. | Notes cannot be audited from the human-readable case files. |
| AUD-005 | High | `read_case_state` returns only `finding_count`, open TODOs, and ten recent notes. It does not return Finding details or completed TODOs. There are no list/get Finding or Note tools. | After compaction or resume the model cannot reliably inspect the state it is expected to maintain. |
| AUD-006 | High | Automatic fallback notes may include model error prose and bounded tool payloads, but there is no semantic checkpoint schema or quality validation. | Tool failures and noise are promoted into permanent “progress.” |
| AUD-007 | Medium | State writes are atomic per file, but the JSON state and derived Markdown set are not one transaction. | Case views can disagree after interruption or partial failure. |
| AUD-008 | Medium | Read-modify-write operations do not expose a state revision or idempotency key. | Retries and multiple processes can create duplicates or overwrite newer state. |
| AUD-009 | Medium | Existing tests prove happy paths but do not inject renderer failure, interruption between writes, duplicate retries, corrupt state, or real Gemma malformed arguments. | Green tests currently overstate reliability. |
| AUD-010 | Medium | `maldroid cases` currently lists cases; it does not open the configured directory. | The requested daily navigation workflow is missing. |
| AUD-011 | Medium | Tool errors are visible in the terminal but lack a stable error ID linking UI, session JSONL, MCP response, and audit log. | Debugging user reports requires manual correlation. |
| AUD-012 | Medium | Profile playbooks exist but are short and retrieval is mostly query-driven. | The model does not consistently receive the method needed for multi-step investigations. |

Planning-audit reproduction:

```text
Valid save_finding payload with evidence.description: completed, FIND-0001 stored.
Same payload without evidence.description: invalid_arguments at evidence.0.description.
Rendered FINDINGS.md for the valid payload: evidence and tags were absent.
```

`REL-010` must reproduce the owner's actual macOS failure before changing the contract. The audit
above supplies a known synthetic reproduction but is not a substitute for the real session.

## 3. Product standard: what “trustworthy” means

MalDroid is not ready to be called a dependable research platform until all of these are true:

- A completed state-tool response means canonical state and every derived view agree.
- A failed state-tool response means no mutation occurred, or it clearly reports a committed
  revision and is safe to retry.
- Every mutation is idempotent or has deterministic duplicate detection.
- Every Finding can be read back through MCP and includes evidence, provenance, confidence, status,
  timestamps, and revision.
- Evidence references are validated against case policy and have actionable error messages.
- Automatic checkpoints use a typed structure and cannot consist only of tool names/errors.
- Tool errors stay in error/audit streams and are not silently converted into research notes.
- After compaction or restart, the model can enumerate and retrieve all durable work.
- Long investigations demonstrate TODO creation, Finding updates, verification, and completion in
  both the terminal and case files.
- Every supported platform has crash, migration, installer, and end-to-end acceptance coverage.
- Arbitrary Python is never described as sandboxed unless OS-level escape tests prove that claim.

## 4. Fifteen implementation gates

### Gate 1 — Reproduce and specify durable-state failures

#### `REL-010` Capture the real macOS failure

- Obtain the failing case path from the owner without copying malware into the repository.
- Save sanitized copies of the session tool-call/result events, `tools.jsonl`, state schema/version,
  and relevant Markdown before retrying anything.
- Record exact installed commit, Python, llama.cpp version, model template, profile, and MCP path.
- Re-run the failing Finding call through `maldroid mcp test`/a minimal local client when safe.
- Classify the failure: schema generation, malformed model call, MCP normalization, validation,
  state mutation, Markdown rendering, stale in-memory state, or UI-only display.
- Add a benign fixture reproducing the exact payload shape.

Acceptance:

- A checked-in regression test fails on the pre-fix implementation for the same reason observed on
  macOS.
- `docs/handoffs/CURRENT.md` links the sanitized evidence and names the first fix task.
- No fix is mixed into the reproduction commit.

#### `REL-011` Define persistence invariants and state authority

- Declare `.maldroid/state.json` canonical or replace it through a migration ADR.
- Declare `CASE.md`, `FINDINGS.md`, `TODO.md`, and summaries as derived views.
- Specify success/failure semantics for every mutation.
- Specify revision, timestamp, idempotency, locking, backup, and recovery behavior.
- Define whether case state can be mutated by more than one process/client.

Acceptance: ADR, sequence diagrams, and executable invariant tests exist before refactoring.

#### `REL-012` Implement transactional state mutations

- Introduce one `CaseStateStore` transaction API for Note/Finding/TODO/summary/evidence changes.
- Lock the entire read-modify-write transaction, not only individual file replacement.
- Validate the next state fully before commit.
- Write canonical state atomically, then render derived views from the committed revision.
- If view rendering fails, preserve committed state and return an explicit `view_degraded` result
  rather than a false generic execution failure.
- Add monotonic `state_revision` and mutation ID.

Acceptance: kill/fault injection at every write boundary never yields ambiguous duplicate state.

#### `REL-013` Make Finding schemas model-friendly

- Study real Gemma 4 tool calls, not only hand-authored payloads.
- Make evidence descriptions optional with a safe generated default, or split minimal and advanced
  evidence forms.
- Add field descriptions and examples to JSON Schema.
- Return precise validation repair guidance including field path, allowed values, and example.
- Normalize common capitalization and enum mistakes only when unambiguous.
- Reject unknown evidence paths through case policy with a precise error.

Acceptance: valid minimal, full, malformed, and repair/retry flows pass through real MCP and Gemma.

#### `REL-014` Validate evidence references

- Validate path existence/registration, line and offset ordering, bounds where cheaply knowable,
  and mutually coherent range types.
- Store tool provenance and a content/source revision where possible.
- Distinguish exact evidence, heuristic support, and unverified references.
- Add `MalDroid_validate_evidence_reference` for preflight.

Acceptance: no confirmed Finding can silently cite a missing or escaped path.

#### `REL-015` Add idempotent mutations and duplicate detection

- Add optional client mutation keys to all write tools.
- Repeated identical keys return the original record without creating a duplicate.
- Detect near-duplicate Findings by normalized title/evidence and return merge guidance.
- Make automatic checkpoint IDs deterministic per phase/revision.

Acceptance: simulated MCP retries create exactly one logical record.

#### `REL-016` Rebuild every human-readable case view

- Render Findings with full evidence, tags, confidence, severity, status, timestamps, revisions, and
  source tools.
- Render Notes with kind, timestamps, evidence, related Findings/TODOs, and next action.
- Render TODOs with priority, dependencies, owner (`model`, `user`, `system`), status, timestamps,
  and completion reason.
- Use atomic writes and deterministic ordering.
- Add `maldroid case rebuild-views [PATH]`.

Acceptance: snapshot tests prove JSON and Markdown parity for all fields.

#### `REL-017` Add complete state read APIs

- `MalDroid_list_findings` with status/tag/confidence filters and pagination.
- `MalDroid_get_finding` by ID.
- `MalDroid_list_notes` and `MalDroid_get_note`.
- `MalDroid_list_todos` including completed items and filters.
- `MalDroid_get_case_revision` and compact state digest.
- Return stable IDs and pagination metadata.

Acceptance: a model with empty conversation can reconstruct current work using MCP only.

#### `REL-018` Complete state mutation APIs

- Add explicit typed update schemas instead of unrestricted `changes: dict`.
- Add resolve/reject/reopen/archive operations for Findings.
- Add update/archive operations for Notes.
- Add edit/reprioritize/block/complete operations for TODOs.
- Avoid hard deletion by default; keep tombstones/audit history.

Acceptance: every mutation is validated, revisioned, auditable, and reversible where practical.

#### `REL-019` Add case consistency doctor and repair

- `maldroid case check [PATH]` verifies schema, IDs, revisions, references, indexes, views, session
  links, and evidence targets.
- `--repair` rebuilds derived artifacts and indexes without fabricating research content.
- `--json` emits stable machine-readable diagnostics.
- Back up state before repair.

Acceptance: corrupt/missing Markdown is repaired; corrupt canonical state is reported, never hidden.

#### `REL-020` Add migration, backup, and recovery coverage

- Version every new persisted shape.
- Add forward migrations and compatibility fixtures for every prior schema.
- Keep last-known-good state and checksums.
- Detect truncated/corrupt JSON and offer read-only recovery.
- Test moved case directories and old registries.

Acceptance: upgrade/downgrade policy is documented and fixtures survive every supported migration.

### Gate 2 — Make Notes, Findings, and TODOs meaningful

#### `STATE-010` Introduce typed checkpoint records

Checkpoint fields must include objective, completed work, evidence learned, Findings changed, TODOs
changed, failed approaches, unresolved questions, uncertainty, and exact next action. A free-form
note remains available for humans but is not the controller's continuity primitive.

#### `STATE-011` Separate record kinds

Add explicit kinds such as `research_note`, `checkpoint`, `decision`, `hypothesis`, `tool_error`,
and `user_note`. Tool errors belong in audit/error records, not in research notes.

#### `STATE-012` Add deterministic checkpoint quality validation

- Reject automatic checkpoints containing only tool names, status messages, or repeated errors.
- Require at least one substantive completed/learned/remaining field.
- Require a next action unless the task is explicitly complete.
- Deduplicate repeated phase checkpoints.
- Never invent a Finding to satisfy a quota.

#### `STATE-013` Link state records

Add related Finding IDs, TODO IDs, evidence IDs, session ID, tool-call IDs, phase, and state revision.

#### `STATE-014` Add checkpoint inspection UX

Show concise checkpoint cards in `/checkpoints`; allow expanding evidence, changed records, errors,
and continuation instruction without dumping raw JSON.

#### `STATE-015` Add state quality telemetry

Expose counts for orphan references, duplicate Findings, stale TODOs, automatic fallback usage,
failed mutations, and view degradation. Keep telemetry local to the case.

#### `STATE-016` Make final-answer enforcement evidence-aware

- Require a fresh checkpoint only after substantive work since the last revision.
- Require Finding creation/update only when a supported conclusion exists.
- Require TODO updates only for real planned work.
- Do not force meaningless records for one-step informational answers.

Acceptance for Gate 2: a 30-minute fixture investigation produces useful, non-duplicated state that
another model instance can resume without reading chat history.

### Gate 3 — Upgrade the agent controller

#### `AGENT-010` Add explicit planner/worker/verifier states

- Planner creates bounded TODOs and selects relevant guides/tools.
- Worker gathers evidence and updates state incrementally.
- Verifier challenges conclusions, checks references, closes TODOs, and prepares final output.
- State transitions are visible in the CLI and session log.

#### `AGENT-011` Add task completion criteria

Define complete, partial, blocked, and needs-user-input with evidence. The model must not stop merely
because a tool window ended, nor loop when the objective is already satisfied.

#### `AGENT-012` Add tool-error recovery policy

- Classify invalid arguments, unavailable dependency, unsupported format, timeout, path denial,
  parse failure, and internal defect.
- Feed concise repair hints back to the model.
- Limit identical retries and automatically switch to a safe alternative.
- Surface a stable error ID to the user.

#### `AGENT-013` Add stuck-loop detection

Detect repeated identical calls, unchanged results, repeated empty searches, duplicate state writes,
and compaction-without-progress. Save a diagnostic checkpoint and choose a different strategy.

#### `AGENT-014` Improve context and evidence budgeting

Account for tool schemas, reasoning, reserved completion, external MCP schemas, and result payloads.
Prefer dropping redundant tool results over early full compaction. Show why compaction occurred.

#### `AGENT-015` Add investigation strategy selection

Route by artifact, framework, goal, available tools, and existing state. Mixed applications may need
more than one sub-strategy while exposing only the current bounded tool set.

#### `AGENT-016` Add verifier passes

Before confirming a Finding, verify cited paths/ranges, contradictory evidence, confidence, and
whether the claim exceeds tool output. Record verification status.

#### `AGENT-017` Add pause/resume durability tests

Interrupt at model generation, tool execution, state commit, checkpoint, compaction, and process
shutdown. Resume the same objective without duplicate writes or lost next action.

#### `AGENT-018` Add user-control commands

Support pause, cancel-current-tool, continue, show-plan, skip-TODO, mark-blocked, and explain-last-
decision. Cancellation must terminate child processes and preserve state.

### Gate 4 — Take the CLI fifteen levels forward

#### `CLI-010` Make `maldroid cases` open the cases directory

Required behavior:

- `maldroid cases` opens `general.cases_directory` in Finder on macOS and the default file manager
  through `xdg-open` on Kali/Linux.
- Use an argument array and `shell=False`.
- Create the configured directory if missing after clear user-facing confirmation/policy.
- Print the exact path before/after opening.
- On a headless system, print the path and a clear non-destructive warning.
- Preserve automation: `maldroid cases --list` renders the current table and `--json` returns the
  existing list payload.

Acceptance: macOS and Linux mocked opener tests plus a physical macOS smoke test.

#### `CLI-011` Add an interactive case picker

Search, sort, preview profile/findings/TODOs/last activity, open folder, resume case, copy path, and
repair/check a selected case.

#### `CLI-012` Build a real investigation dashboard

Show phase, objective, current TODO, active tool, elapsed time, model tokens, context, state revision,
Findings changed, errors, child processes, and connected MCP servers without flicker.

#### `CLI-013` Add expandable activity views

Default output stays concise. A key/command expands tool arguments, bounded result preview, output
file, duration, error details, and related Finding/TODO/checkpoint.

#### `CLI-014` Improve errors and recovery guidance

Every error should state what failed, whether state changed, what MalDroid will try, what the user
can do, and the error/audit ID. Never dump `TaskGroup` or raw stack prose in normal mode.

#### `CLI-015` Add first-run and empty-state guidance

Explain cases, evidence, profiles, MCP, model state, and the first useful command without requiring
prior project knowledge.

#### `CLI-016` Add case report/export UX

Export a sanitized Markdown/JSON report, evidence-reference manifest, Findings, TODOs, versions, and
limitations. Never include evidence bytes unless explicitly requested.

#### `CLI-017` Make slash commands discoverable and composable

Add aliases, argument completion, inline help, fuzzy selection, command history, and consistent JSON
equivalents. Ensure non-TTY behavior remains deterministic.

#### `CLI-018` Add session replay and explainability

`/timeline` should show user prompts, planning decisions, tools, state mutations, checkpoints,
compactions, retries, and final responses with filters—not hidden reasoning text.

#### `CLI-019` Add performance budgets

Measure startup, MCP discovery, first token, tool latency, render cost, and shutdown. Slow external
MCP discovery remains parallel and bounded.

#### `CLI-020` Accessibility and terminal compatibility

Test Terminal.app, iTerm2, common Kali terminals, no-color, narrow widths, screen readers, redirected
output, Unicode-disabled environments, and Ctrl-C/Ctrl-D/SIGHUP behavior.

### Gate 5 — Design safe Python decoding scripts

The owner explicitly wants the agent to write and run Python for decoding and research helpers.
This is powerful and dangerous. `python -I`, `shell=False`, AST filtering, a virtual environment,
and a controlled working directory are not security sandboxes: Python can still access files,
processes, and the network unless the OS prevents it. Do not claim otherwise.

#### `PY-010` Write the execution-threat ADR

Decide between:

1. a restricted built-in transform API for default autonomous decoding;
2. OS-sandboxed arbitrary Python where a verified backend exists;
3. explicitly trusted host Python requiring owner opt-in where isolation is unavailable.

Document macOS and Kali differences and what “network disabled” actually guarantees.

#### `PY-011` Add case-local script provenance

Scripts live under `workspace/scripts/`; store source hash, creator, objective, inputs, outputs,
Python version, packages, timestamps, approval mode, exit code, and related state IDs.

#### `PY-012` Add `MalDroid_write_python_script`

- Write only inside the script directory through path policy.
- No overwrite without revision/history.
- Return a diff, hash, and static risk scan.
- Never execute during the write call.

#### `PY-013` Add a restricted transform library

Provide safe primitives for hex/base64/base32, XOR, byte rotation, URL encoding, compression,
checksums, string tables, endian conversion, protobuf/JSON/XML parsing, and bounded binary slicing.
Prefer these tools over arbitrary Python.

#### `PY-014` Add `MalDroid_run_python_script`

- Argument arrays only; no shell.
- Explicit input/output paths; bounded stdout/stderr; timeout; memory/CPU/file-size/process limits.
- Minimal environment and controlled working directory.
- Kill the entire process group on timeout/cancel/exit.
- Save outputs and execution audit in the case.
- Reject evidence execution; scripts may read evidence only as data.

#### `PY-015` Implement and verify OS isolation

- Research a maintained macOS sandbox approach and Kali `bubblewrap`/equivalent.
- Deny network, unrelated filesystem paths, process spawning, device access, and environment secrets.
- If a platform cannot enforce a boundary, label the mode trusted/unrestricted and require explicit
  configuration/approval; do not silently fall back.

#### `PY-016` Add adversarial escape tests

Attempt `open('/etc/passwd')`, home-directory reads, symlink escape, sockets, DNS, subprocesses,
fork bombs, huge allocation/output, signals, `/proc`, environment secrets, and interpreter tricks.

#### `PY-017` Add script UX

Show source/diff, risk level, inputs, live bounded output, runtime, outputs, and exact isolation mode.
Allow rerun, edit, cancel, archive, and promote a useful script into a reviewed local template.

Gate 5 acceptance: arbitrary Python is disabled unless its displayed execution mode matches tested
reality. Restricted decoding remains available without host-level authority.

`PLATFORM-015` status: `PY-010` selects restricted built-in transforms as the only autonomous path.
The write-only portions of `PY-011`/`PY-012` are implemented with `SCRIPT-xxxx` provenance,
source hashes/diffs, private append-only files, AST risk findings, explicit `not_executed` status,
and deterministic CLI/final-answer disclosure. `PY-014` through `PY-016` remain unimplemented;
there is no run tool, OS-isolation claim, or execution approval mode.

### Gate 6 — Expand core static-analysis tools

Each tool below requires bounded I/O, typed schemas, structured results, exact/heuristic labeling,
audit, hostile fixtures, documentation, and profile filtering where relevant.

- `TOOL-010`: file type/magic classifier with confidence and conflicting-extension detection.
- `TOOL-011`: bounded hex/byte-range reader with offsets and ASCII preview.
- `TOOL-012`: safe archive inventory for ZIP/APK/AAB/APKS with zip-slip/bomb defenses.
- `TOOL-013`: selective safe archive extraction into case workspace with size/count/ratio limits.
- `TOOL-014`: cheap hashes on demand plus sampling strategy for very large files.
- `TOOL-015`: entropy and byte-frequency windows for packed/encrypted-region triage.
- `TOOL-016`: encoding/escaping detector and bounded decoder chain with provenance.
- `TOOL-017`: compression detector/decompressor for explicitly supported data blobs.
- `TOOL-018`: structured JSON/XML/plist/INI/YAML readers with query and bounded ranges.
- `TOOL-019`: SQLite schema/table/query inspection in immutable read-only mode.
- `TOOL-020`: protobuf descriptor-aware and heuristic wire inspection with uncertainty labels.
- `TOOL-021`: URL/domain/IP/email/intent/component/permission IOC extraction and deduplication.
- `TOOL-022`: cross-file reference correlation and evidence graph creation.
- `TOOL-023`: file and directory diff with large-file safeguards.
- `TOOL-024`: safe YARA scanning adapter with reviewed rules, versions, and no repository malware.
- `TOOL-025`: source-map detection, validation, mapping, and bounded original-source reads.
- `TOOL-026`: certificate/signature metadata and trust-chain reporting.
- `TOOL-027`: artifact inventory manifest with hashes, types, sizes, and analysis coverage.
- `TOOL-028`: report builder from verified Findings and evidence references.

`PLATFORM-014` status: `TOOL-010`, `TOOL-018`, and `TOOL-019` are implemented. The non-extracting portion of
`TOOL-012` is implemented with duplicate, encrypted, path-traversal, size, and compression-ratio
reporting plus bounded in-memory entry reads. `PLATFORM-015` implements `TOOL-016` for supported
Base64/Base32/hex/URL/Unicode/ROT13, byte/XOR/rotation, and gzip/zlib/bzip2/LZMA stages with
per-stage provenance plus source-literal/pipeline detection. `TOOL-014`, `TOOL-015`, `TOOL-023`,
and `TOOL-025` have useful bounded first slices but still lack, respectively, very-large-file sampling
hashes, entropy windows, directory diff, and decoded source mappings. `TOOL-011`, `TOOL-021`, and
`TOOL-028` were implemented earlier. Selective extraction, decompression, protobuf, correlation
graphs, YARA, certificate/signature metadata, and complete coverage manifests remain open. New
lexical large-source summary, dependency-map, and symbol-trace tools supplement this backlog but do
not claim a parsed call graph.

### Gate 7 — Android package, manifest, resource, and DEX depth

- `APK-010`: APK/AAB/APKS split inventory and package relationships.
- `APK-011`: binary AndroidManifest parsing without requiring pre-extraction.
- `APK-012`: permission/component/intent-filter/provider/exported-state analysis.
- `APK-013`: AccessibilityService, device-admin, VPN, notification-listener, overlay, and boot-flow
  static triage.
- `APK-014`: resources.arsc/string/resource-reference resolution.
- `APK-015`: signing scheme/certificate metadata and signer comparison.
- `DEX-010`: DEX header/map/class/method/string inventory with multidex support.
- `DEX-011`: exact string/type/method cross-reference search.
- `DEX-012`: bounded method disassembly and control/reference summary.
- `DEX-013`: Java/Kotlin metadata and coroutine/serialization indicators.
- `DEX-014`: Smali directory indexing, symbol search, call/reference tracing, and bounded reads.
- `DEX-015`: allowlisted jadx/apktool adapter with version compatibility and output indexing.
- `DEX-016`: reflection/dynamic-loader/native-loader static indicators without dynamic execution.
- `DEX-017`: manifest-to-code component entrypoint tracing.
- `DEX-018`: rule-assisted suspicious capability map that always cites exact evidence.

### Gate 8 — Deepen framework and native profiles

#### React Native

- Version-aware Metro module parsing and dependency graph.
- Hermes bytecode header/version detection and compatible static disassembler adapters.
- Source-map reconstruction, module naming, navigation/bridge/native-module tracing.
- Obfuscation/minification confidence and unsupported-format explanations.

#### Native

- ELF program headers, relocations, imports/exports, dynamic tags, build IDs, hardening, and ABI.
- JNI registration/native method mapping and Java-to-native correlation.
- Bounded disassembly/function/call graph through allowlisted tools.
- Rust/Go/C++ indicators, strings/xrefs, and library version fingerprints.

#### Flutter

- Exact artifact/version detection, snapshot metadata, asset/config inspection, ABI selection.
- Blutter compatibility matrix, deterministic invocation, indexed output, symbol/xref tools.

#### Unity

- Reliable Mono versus IL2CPP workflows, metadata versioning, managed assemblies, symbols, and
  method/type correlation.

#### Cordova and Cocos

- Plugin/bridge/config/allowlist/URL tracing for Cordova.
- JavaScript/Lua/bytecode/native-binding detection, versioning, decoding support, and unsupported
  encryption reporting for Cocos.

Every profile must have real benign fixtures across versions, not filenames that only satisfy a
detector test.

### Gate 9 — Build a serious investigation knowledge system

Every guide must contain artifacts, prerequisites, triage questions, exact workflow, tool sequence,
decision points, exact versus heuristic claims, evidence requirements, failure modes, unsupported
versions, escalation, sources, and `last_verified`.

Required guide tasks:

- `KB-010`: general static investigation lifecycle and definition of sufficient evidence.
- `KB-011`: hypothesis formation, falsification, confidence, and contradiction handling.
- `KB-012`: Android package/split/signing triage.
- `KB-013`: manifest, permissions, components, and exported attack surface.
- `KB-014`: AccessibilityService investigation end to end.
- `KB-015`: device-admin, overlay, VPN, notification listener, boot, and persistence capabilities.
- `KB-016`: DEX/Java/Kotlin and Smali tracing.
- `KB-017`: reflection, loaders, encrypted assets, and static limitations.
- `KB-018`: network configuration, URLs, certificates, WebViews, and API client tracing.
- `KB-019`: cryptographic/encoding triage without overstating plaintext recovery.
- `KB-020`: React Native Metro workflow.
- `KB-021`: Hermes version/bytecode workflow.
- `KB-022`: Flutter AOT and Blutter workflow by version/ABI.
- `KB-023`: Unity Mono/IL2CPP workflow.
- `KB-024`: Cordova bridge/plugin workflow.
- `KB-025`: Cocos JavaScript/Lua/native workflow.
- `KB-026`: ELF/JNI/C/C++/Rust/Go native workflow.
- `KB-027`: large-file search/index/correlation strategy.
- `KB-028`: source maps, decompiler exports, logs, and mixed artifact sets.
- `KB-029`: prompt injection and hostile evidence handling.
- `KB-030`: tool failure and unsupported-format recovery.
- `KB-031`: writing Findings, evidence references, TODOs, checkpoints, and final reports.
- `KB-032`: safe decoding-script design and when not to execute Python.
- `KB-033`: verification checklist before confirming a security conclusion.

#### `KB-034` Add automatic guide routing

Select small relevant excerpts by active profile, detected artifacts, current TODO, and tool error.
Do not dump entire playbooks into context. Record which guide/version influenced a decision.

#### `KB-035` Add knowledge quality CI

Validate front matter, sources, dates, internal tool names, unsupported claims, stale compatibility,
and fixture-backed examples.

### Gate 10 — Make model activity transparent without exposing hidden reasoning

- `OBS-010`: one correlation ID from model request through tool call, MCP, state mutation, UI, and
  audit.
- `OBS-011`: structured timeline events for plan, tool, result, retry, state change, checkpoint,
  compaction, profile, external MCP, and child process.
- `OBS-012`: show concise decision summaries and evidence used, not private reasoning tokens.
- `OBS-013`: accurate prompt/completion/reasoning/context metrics from server usage where available.
- `OBS-014`: tool duration, output size, truncation, cache/index hit, and saved output path.
- `OBS-015`: local diagnostic bundle exporter that redacts evidence content and secrets.
- `OBS-016`: `/errors`, `/timeline`, `/state`, and `/processes` terminal views.
- `OBS-017`: rotate/limit logs without losing the active handoff or mutation audit.

### Gate 11 — Security and policy review

- Threat-model internal tools, external MCP, WebUI host tools, Python execution, archives, parsers,
  decompilers, symlinks, case moves, logs, and prompt injection.
- Add per-capability authority labels in `/tools`.
- Separate case-scoped, external-MCP, trusted-host, and sandboxed-script authorities visually and in
  schemas/prompts.
- Add secret redaction for URLs, environment, logs, commands, diagnostic bundles, and reports.
- Verify no evidence/network upload paths were introduced.
- Add dependency and license inventory for distribution.

### Gate 12 — Testing overhaul

- `QA-010`: direct state-tool protocol tests for minimal/full/malformed real-model payloads.
- `QA-011`: state transaction fault injection at every write/render boundary.
- `QA-012`: idempotency, duplicate retry, stale revision, and multiprocess concurrency tests.
- `QA-013`: property/fuzz tests for IDs, ranges, archives, encodings, parsers, and migrations.
- `QA-014`: golden Markdown/state parity snapshots.
- `QA-015`: prompt-injection fixtures across filenames, content, tool descriptions, and external MCP.
- `QA-016`: 30-minute synthetic agent run with context rollover, resume, state verification, and no
  meaningless notes.
- `QA-017`: real Gemma 4 tool-call suite including arrays, nested evidence, repair, and state reads.
- `QA-018`: Python escape/resource/network/process adversarial suite.
- `QA-019`: macOS/Kali opener, terminal, installer, upgrade, uninstall, and signal lifecycle tests.
- `QA-020`: benign version matrix for APK/DEX/framework/native tools.
- `QA-021`: performance regression budgets for startup, indexing, tool calls, and rendering.
- `QA-022`: wheel installation into clean temporary HOME with global pip misconfiguration.
- `QA-023`: repository contains no real malware and CI never executes fixture artifacts.

### Gate 13 — Documentation and distribution quality

- Rewrite the README around first success, daily workflow, authority boundaries, and recovery.
- Add a five-minute tutorial using a benign fixture.
- Document every command and tool with examples and failure behavior.
- Add troubleshooting keyed by stable error codes.
- Add upgrade/migration/backup/recovery guides.
- Add a tool/profile compatibility matrix generated from code and verified versions.
- Add release notes, signed/tagged release process, checksums, and uninstall data-retention table.

### Gate 14 — Physical target acceptance

On the owner's current macOS machine and Kali:

- Install from a clean public clone.
- Run real Gemma 4 with the approved 65,536 context command.
- Complete an AccessibilityService case, a large React Native bundle, a DEX/Smali case, and one
  native/framework case.
- Run for at least 30 minutes, interrupt/resume, trigger one compaction, and verify state parity.
- Verify Findings/TODOs/Notes are useful to a fresh session.
- Verify `maldroid cases` opens Finder/file manager.
- Verify external MCP and Python authority labels match reality.
- Record tool versions, timings, bugs, and acceptance evidence in the repository.

### Gate 15 — Trust release

Do not label the release stable until:

- all critical/high state findings are closed;
- real-model and physical-platform acceptance pass;
- no silent/ambiguous mutation failure remains;
- Python isolation claims are proven or explicitly labeled trusted-only;
- supported formats have honest compatibility/unsupported behavior;
- a new agent can resume using repository state and handoff alone;
- the owner confirms the CLI is usable for a real research workflow.

## 5. Required execution order

The first dependency chain is mandatory:

```text
REL-010 → REL-011 → REL-012 → REL-013 → REL-014 → REL-015
        → REL-016 → REL-017 → REL-018 → REL-019 → REL-020
        → STATE-010..016 → AGENT-010..018
```

`CLI-010` may be implemented after `REL-010` because it is isolated and low risk. Knowledge research
may proceed only when it does not delay the reliability chain. Python implementation must not begin
before `PY-010` is accepted. Broad tool additions must not begin before state mutation and readback
are trustworthy, otherwise they will produce more unauditable noise.

## 6. Git workflow for every future agent

### Start of task

1. Read `AGENTS.md`, this file, `Tasks.MD`, `ARCHITECTURE.md`, `PROJECT_STATUS.md`, `DECISIONS.md`,
   `NEXT_STEPS.md`, and `docs/handoffs/CURRENT.md` completely.
2. Run:

   ```bash
   git status --short --branch
   git log -5 --oneline
   git fetch origin
   git pull --ff-only origin main
   ./scripts/dev doctor
   ./scripts/dev test
   ```

3. Stop if the working tree contains unexplained changes. Never reset, discard, or overwrite another
   agent's work.
4. Confirm `HEAD` equals the commit named in the handoff.
5. Claim exactly one dependency-ready task ID in `NEXT_STEPS.md`/handoff.
6. Preserve the repository's sequential workflow. Do not run multiple editing agents concurrently.
7. Do not edit `Tasks.MD`.

### During task

- Reproduce first; write a failing regression test before the fix when possible.
- Keep scope within the selected task ID.
- Use `./scripts/dev`; never system `pip`, `sudo pip`, or untracked environments.
- Use `apply_patch` for intentional edits and preserve unrelated work.
- Route all managed tools through MCP and retain path/output/audit boundaries.
- Use benign fixtures only; never commit malware or proprietary evidence.
- Update technical docs and add an ADR for a significant decision.
- Do not claim security, compatibility, or completion without executable evidence.

### Before commit

Run targeted tests and then:

```bash
./scripts/dev release-check
./.venv/bin/python scripts/check_project_hygiene.py
git diff --check
git status --short
git diff --stat
```

Review the full diff for secret paths, evidence content, generated files, unrelated edits, unsafe
shell use, missing tests, and stale documentation.

### Commit and push

- One atomic commit per task ID.
- Commit format: `TASK-ID concise imperative outcome`.
- Never amend, rebase, force-push, or rewrite a commit already handed off.
- The established repository workflow currently pushes verified atomic commits to `main`; do not
  silently change it. If branch protection/PR workflow is introduced, document it in an ADR and
  handoff first.
- Push only after release checks pass, then wait for both macOS and Kali CI.

Example:

```bash
git add <intentional-files>
git commit -m "REL-010 reproduce finding persistence failure"
git push origin main
gh run list --branch main --limit 2
gh run watch <run-id> --exit-status
```

### Mandatory handoff

Update:

- `PROJECT_STATUS.md`: facts only; completed/partial/missing/known defects.
- `NEXT_STEPS.md`: dependency-ready next task first.
- `CHANGELOG.md`: user-visible changes only.
- `docs/handoffs/CURRENT.md`: task, commit, files, tests, limitations, dirty-tree state, and exact
  first command for the next agent.
- This master plan: mark only genuinely completed tasks and add newly discovered work without
  deleting owner requirements.

The final message to the owner must state outcome, tests, commit, CI, remaining limitations, and how
to update the installed copy. Do not say a bug is fixed when only synthetic tests passed and target
acceptance remains open.

## 7. Definition of done for an individual task

A task is done only when:

- the reported behavior is reproduced or the requirement has a precise executable specification;
- implementation, negative tests, adversarial tests, and regression tests are complete;
- state/migration/security implications are addressed;
- CLI and JSON behavior are documented;
- relevant macOS/Kali behavior is tested or explicitly environment-gated;
- release check and hygiene pass;
- documentation/handoff are current;
- working tree is clean after an atomic commit;
- pushed CI passes;
- no stub, placeholder, mock-only implementation, or hidden unsupported path is presented as done.

## 8. First command for the next agent

```bash
git status --short --branch && git log -5 --oneline && ./scripts/dev test
```

Then begin the physical CLI-focused `PLATFORM-011` acceptance described in `NEXT_STEPS.md`. Keep Web
feature work on hold. After that acceptance, return to `REL-010`; do not change the Finding schema
before capturing the owner's exact failing tool call and persistence artifacts.
