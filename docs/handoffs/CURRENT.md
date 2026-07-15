# Current Handoff

Task: `WEB-003`
Next task: `PLATFORM-011`

Implementation commit: pending

## Outcome

The owner reprioritized MalDroid around real multi-hour research usability. The local implementation
now provides semantic research memory, bounded long-run context, a faster interactive research CLI,
deep React Native and Native/Ghidra guidance, and focused large-evidence tools.

The repository now also has a modern local Web product surface. `maldroid server` serves an English
three-pane workspace with investigation conversations, multilingual/RTL chat, bounded files,
research state, activity, settings, reports, and MCP connectors. Bare `maldroid` asks for Web or
CLI; `maldroid cli` selects the terminal explicitly.

## Web usability follow-up

- Fixed the root cause of the missing chat box: the legacy adjacent-sibling CSS rule continued to
  hide the composer after runtime activation. Explicit active/hidden state now wins, the composer is
  labeled `Message MalDroid`, an empty conversation explains where to start, and readiness focuses
  the input with a clear toast.
- Added persistent Dark/Light appearance through the header and Workspace Settings. The preference
  stays in browser `localStorage` and does not pollute case or model configuration.
- Rebuilt Files presentation around the existing bounded API: name/path filter, result count,
  collapsible directories, type-aware icons, selected-file highlight, keyboard controls, truncation
  notice, and the same bounded preview.
- A collapsed project sidebar now exposes the existing header menu button on desktop. Explicit grid
  columns prevent the workspace and inspector from shifting when the sidebar is hidden; mobile
  placement remains single-column.
- Local browser verification covered 1280×720 Dark and Light rendering, exact light background,
  collapse/restore state, grid columns, and browser console errors. Only the Codex Electron host's
  generic development CSP warning appeared; the MalDroid page logged no application error.

## Responsive 100%-zoom follow-up

- Replaced the fixed 268/372px side panes and 420px chat minimum with clamped fluid columns and a
  `minmax(0, 1fr)` chat column. The shell uses the dynamic viewport height and cannot exceed the
  viewport width through its grid definition.
- At 900px and below, Chat is the only document column. Projects and the complete
  Files/Research/Activity inspector are fixed drawers with independent open/close controls,
  synchronized ARIA state, mutually exclusive opening, and resize-safe desktop/mobile state.
- At 560px and short-screen breakpoints, secondary header/status and decorative welcome elements
  compact while project access, inspector access, theme, and the eventual composer remain present.
- Browser verification at 100% covered 1280×720, 1024×768, 900×700, 768×700, and 390×844. Every
  viewport reported `scrollWidth <= innerWidth`; the 1024 layout measured 216px Projects, 516px
  Chat, and 292px inspector, while compact widths gave Chat the full viewport. Drawer open/close
  geometry was also verified. The viewport override was reset afterward.

## Repeated-output recovery

- The local streaming client examines only the final 8,192 characters of answer and reasoning
  channels. Six strongly repeated words/phrases or an extreme repeated-character suffix stops the
  stream before the response consumes the remaining token budget.
- Detection metadata contains only channel and size/count values. The partial repeated output is
  never appended to assistant history, Notes, Findings, TODOs, or Checkpoints.
- The controller saves at most 24,000 characters of durable case state, creates a new
  `SessionManager`, restores the active objective, and continues the same turn with a
  non-repetition instruction. At most 10,000 characters of recent retained tool results enter only
  the new working context as explicitly untrusted data; they are not written to the persistent
  summary or semantic research records.
- Recovery is limited to two fresh sessions per turn. A third loop returns a controlled message
  while keeping all durable state. This signal bypasses ordinary transient-request backoff.
- `llama.repetition_recovery_enabled` defaults to `true`. It is discoverable through CLI config and
  exposed as an English checkbox in Web Model Settings. Settings remain editable only while the
  active model runtime is stopped, consistent with all persistent Web settings.
- CLI status and Web Activity show detection, recovery session changes, and safe exhaustion. No
  hidden reasoning or repeated content is exposed.
- ADR 0015 records the streaming threshold, clean-session boundary, persistence policy, attempt
  limit, and opt-out.

## One-command update

- `maldroid update` clones only the fixed official GitHub repository's `main` branch with depth one.
- The clone lives in `TemporaryDirectory` and is removed after both successful and failed installs.
- It invokes `install.sh --upgrade` with the base interpreter and no setup/PATH prompts.
- Upgrade keeps the existing private venv as `venv.previous`, restores it on failure, and deletes
  the backup only after the new installation and doctor step succeed.
- The global runtime lease blocks update while CLI or Web is active. Config, cases, knowledge, and
  external MCP state are not stored in the venv and remain unchanged.
- ADR 0014 records the explicit-network, fixed-origin, rollback, and cleanup boundaries.

## Web runtime and security

- `WorkspaceRuntime` is shared by CLI and Web and owns llama.cpp, local MCP, official MCP client,
  external MCP, session, and agent lifecycle.
- `RuntimeLease` prevents simultaneous CLI/Web workloads and remains held until model shutdown.
- Web binds only to `127.0.0.1`, starts without loading the model, and keeps one active case runtime.
- A random token is exchanged for an HTTP-only SameSite cookie. API/WS auth, Trusted Host checks,
  CSP, no-store, frame blocking, and content-type protections are enabled.
- File tree and preview calls use the dispatcher and `PathPolicy`; evidence execution remains
  forbidden. Agent events stream to Activity without exposing hidden reasoning.
- ADR 0013 documents the shared-runtime and local-Web security decisions. `docs/WEB.md` is the
  operating guide.

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

Updater and transactional-installer contracts:

```text
./scripts/dev test tests/test_updater.py tests/test_cli_process_installer.py
./scripts/dev maldroid update --help
bash -n install.sh
```

Results: 31 focused tests passed. They cover fixed official clone arguments, base-Python selection,
commit reporting, successful temporary-checkout deletion, deletion after installer failure, missing
Git, CLI output, command dispatch, installer help, successful private-venv replacement, and exact
previous-venv restoration after simulated pip failure.

Web-focused contracts:

```text
./scripts/dev test tests/test_web_workspace.py
```

Result: 7 passed. Coverage includes per-run token rejection, project creation/listing, Unicode and
bounded file preview through path policy, authenticated WebSocket bootstrap, global runtime lease,
loopback-only config validation, explicit production WebSocket packaging, and hidden-reasoning
exclusion from timeline output.

Real local browser smoke test:

```text
./scripts/dev maldroid server --port 8787 --no-open
```

Result: the packaged 1280×720 three-pane workspace and Settings modal rendered correctly; API auth
completed, the real Uvicorn WebSocket connected without server warnings, browser logs contained no
application errors, and the model remained offline until case activation. This test exposed and
fixed the missing explicit `websockets` runtime dependency.

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
./scripts/dev test tests/test_web_workspace.py tests/test_ui.py
./scripts/dev test
```

Results: all focused suites passed. Repetition-specific coverage includes Hebrew words, phrases,
Unicode character runs, normal prose/code/JSON false-positive fixtures, disabled behavior, stream
closure, fresh-session continuation, objective carry-over, and bounded exhaustion. The current full
suite passed with `136 passed`; the focused Web/UI suite passed with `16 passed`.

Release gate:

```text
./scripts/dev release-check
```

The current final run passed Ruff formatting/lint, mypy for 43 source files, 136 tests with 71%
coverage, project hygiene, installer dry-run, wheel build, and archive verification. The wheel is
`dist/maldroid-0.1.0-py3-none-any.whl` (154,539 bytes, SHA-256
`3b919942f6579581186b516b23482fa7aff6710a52c5a1c30082ab82a70e8e91`) and contains the updated
composer, theme, Files explorer, repetition guard, updater, Web server, and all three static assets.
`node --check src/maldroid/web/static/app.js` also passed.

GitHub Actions run `29433131792` passed on macOS 26 and Kali for commit `2f6a537`. Both jobs passed
dependency bootstrap (including the explicit WebSocket backend), Ruff, mypy, formatting, all 115
tests, coverage, and installer dry-run.

GitHub Actions run `29433912079` passed `CLI-011` on macOS 26 and Kali for commit `edde4e5`. Both
jobs passed dependency bootstrap, Ruff, mypy, formatting, all 122 tests, coverage, and installer
dry-run.

GitHub Actions run `29434717235` passed `MODEL-010` on macOS 26 and Kali for commit `84cc788`. Both
jobs passed dependency bootstrap, Ruff, formatting, all 135 tests, coverage, and installer dry-run.

GitHub Actions run `29436270978` passed `WEB-002` on macOS 26 and Kali for commit `e0df862`. Both
jobs passed dependency bootstrap, Ruff, formatting, all 136 tests, coverage, and installer dry-run.

GitHub Actions run `29430555735` passed Kali and exposed one macOS-only failure: the new behavior
search required ripgrep, which the macOS image does not install. Commit `6e4e744` added and tested
the bounded streaming fallback. Replacement run `29430877237` passed both macOS 26 and Kali,
including lint, formatting, all 106 tests, and installer dry-run.

## Known limitations

- No real Gemma 4, llama-server, macOS Terminal, or Ghidra MCP long-run acceptance occurred in this
  Linux workspace.
- Repetition thresholds have deterministic multilingual synthetic coverage but still require tuning
  against real Gemma 4 loops and long legitimate outputs on the owner's macOS host.
- Web UI activation, Hebrew model output, real project switching, and Ghidra MCP execution still
  require the owner's configured macOS model and tools. The local browser smoke test deliberately
  kept the missing Linux model offline.
- The updater's clone/install/rollback behavior is fully exercised with isolated synthetic
  environments, but a real installed macOS self-update from this new command requires the command
  to first be delivered to the owner's installation.
- Canonical state still lacks revision/idempotency/multiprocess transaction semantics from
  `REL-011..020`; schema v2 preserves the existing rollback model.
- Automatic semantic fallback cannot manufacture research meaning. When the model supplies no
  semantic synthesis and no durable Finding/TODO exists, MalDroid skips the checkpoint.
- URL/behavior pattern hits are triage leads, not reachability or maliciousness conclusions.
- React Native Metro parsing remains heuristic and Hermes compatibility remains version-sensitive.
- Internal subagents are not implemented.

## Next command

```bash
./scripts/dev release-check
```

Install current `main` once on the owner's macOS host, run `maldroid update` from the installed
command, and begin `PLATFORM-011` with Web/CLI parity acceptance followed by the real one-hour React
Native and Native/Ghidra MCP work.
