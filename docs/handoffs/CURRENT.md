# Current Handoff

Task: `PLATFORM-013`
Next task: `PLATFORM-011`

Implementation commit: the atomic `PLATFORM-013` commit containing this handoff (see `git log -1`)

## Outcome

The owner requested another complete regression and reliability run. The repository started clean on
`main` at `d93de9e`; the baseline doctor, 147-test suite, and consolidated release gate passed before
edits. The audit then exercised long model turns, shutdown, profile selection, repetition recovery,
large/minified files, filesystem traversal, evidence registration, Web concurrency/reconnect, and
bounded history/log surfaces.

This task fixes the discovered failures and expands deterministic coverage to 186 tests. It does not
claim physical Gemma 4, macOS, or Ghidra MCP acceptance because this Linux workspace has neither the
configured llama-server binary nor the owner's GGUF. That remains `PLATFORM-011`.

## Model/runtime reliability

- Three consecutive identical tool name/argument/result outcomes now emit a strategy-change system
  instruction and visible CLI/Web event. Five stop the turn with a persisted assistant message.
  Completed state remains safe and the loop does not create a junk Note or synthetic Checkpoint.
- Shutdown uses a deterministic summary built from typed case state and never starts a model
  compaction. One marked durable section is replaced on later shutdowns, preserving prior synthesis
  without recursive growth. MCP and llama cleanup continue when summary, session, or one listener
  cleanup step fails.
- Manual profiles cannot be overwritten by forced/model detection. Failed automatic detection is
  retried rather than incorrectly cached as complete. Evidence registration refreshes detection only
  in automatic mode.
- Repetition recovery records the restored user objective as the normal message in the new session,
  runtime/session pointers follow that new session, and exhausted recovery fallbacks are visible in
  chat history.
- Per-run context overrides are validated before case creation/mutation against schema bounds,
  `llama.keep`, and the response-token budget.

## Large repositories and tools

- Broad traversal shares a non-following walker that excludes nested symlinks plus routine `.git`,
  `.maldroid`, `.venv`, `__pycache__`, and `tool-output` trees. Explicit registered evidence roots
  and explicitly requested generated outputs remain available through `PathPolicy`.
- Exact search streams ripgrep output, applies one global result/time budget, handles null-delimited
  paths including embedded newlines safely, and labels early totals as non-exact. The Python
  fallback searches multi-megabyte minified lines in fixed chunks and centers its preview on the
  match. Line-range reads retain bounded prefixes rather than materializing oversized logical lines.
- Behavior triage and network indicator extraction now stop at global budgets and bound the saved
  JSONL/indicator artifact as well as the inline MCP response. Framework, Native, React Native,
  knowledge, external MCP history, CLI timeline/history, and Web session reads avoid whole-file
  materialization where it was unnecessary.
- React Native metrics stream multi-megabyte single lines, head/tail samples no longer overlap, and
  bundle-block overlap cannot duplicate a match. Native subprocess parsing and generated previews
  stream or read bounded prefixes.
- Evidence registration rolls back both the destination and in-memory record when persistence fails,
  immediately refreshes the live evidence mapping on success, and directory sizing ignores nested
  symlinks. Knowledge document keys are explicitly namespaced `builtin/user/case`.

## Web/CLI behavior

- Web activation, direct commands, runtime stop, and model turns are mutually exclusive. Final
  server shutdown requests cancellation and waits for the actual turn boundary instead of
  abandoning a live runtime after an arbitrary timeout; event emission tolerates a closed reconnect
  loop.
- Reconnect/error handling reloads authoritative workspace and bounded history, clears stale
  chat/Files state, serially restores the active case, and labels a failed start **Model offline**.
  WebSocket messages are consumed in arrival order, and reconnect storms from obsolete sockets are
  suppressed.
- Settings now includes **Stop model**, allowing persistent settings to change without closing the
  Web server. The existing Live Work **Stop** continues to cancel only the active turn.
- Conversation history is capped at the latest 500 visible messages and session activity at 5,000
  events while streaming JSONL. Numeric session ordering remains correct after session 9,999.
- The Files explorer keeps latest-turn markers and hidden logs; list/preview paths remain routed
  through the shared dispatcher. CLI/Web display the new tool-loop warning/stop events.
- Runtime-lease acquisition rolls back the lock if metadata persistence fails, preventing a false
  permanent “already running” state.

## Browser verification

- The packaged in-app browser at its real default 1280×720 viewport reported body/root dimensions of
  exactly 1280×720, sidebar/workspace/inspector widths of 243/794/243px, and no horizontal or vertical
  document overflow at 100% zoom.
- The browser-control backend repeatedly timed out on screenshots and ignored its documented
  viewport override; a final post-edit reload also timed out. No unrelated browser backend was used.
  Responsive contracts, Settings markup, Light/RTL controls, reconnect behavior, Files controls, and
  JavaScript syntax are therefore also covered by the static/Web integration suite. The temporary
  loopback server and browser viewport override were stopped/reset; no test runtime remains.

## Architecture and documentation

- ADR 0018 records deterministic shutdown, identical-tool protection, safe traversal, bounded
  artifacts, and authoritative Web/session recovery.
- Updated `ARCHITECTURE.md`, `DECISIONS.md`, `NEXT_AGENT_MASTER_PLAN.md`, `NEXT_STEPS.md`,
  `PROJECT_STATUS.md`, `CHANGELOG.md`, `README.md`, `docs/CLI.md`, and `docs/WEB.md`.
- `Tasks.MD` remains unchanged as required.

## Verification

Startup baseline:

- `git status --short --branch` — clean `main...origin/main` at `d93de9e`.
- `git fetch origin && git pull --ff-only origin main` — already up to date.
- `./scripts/dev doctor` — Python/platform/ripgrep and all configured boundaries passed; expected
  errors reported the absent local llama-server and GGUF.
- `./scripts/dev test` — 147 passed, one upstream Starlette/httpx2 deprecation warning.
- `./scripts/dev release-check` — passed with 147 tests and 72% coverage.

Implementation checks before the final consolidated gate:

- Targeted backend/Web/large-file suites — passed throughout, including an 81-test combined run.
- `./scripts/dev lint` — Ruff passed.
- `./scripts/dev python -m mypy src` — 43 source files passed.
- `./scripts/dev test` — 186 passed in 4.52 seconds; one unchanged Starlette/httpx2 warning.
- `node --check src/maldroid/web/static/app.js` — passed.
- `git diff --check` — passed.

Final gate results are recorded below after the documentation-inclusive run:

- `./scripts/dev release-check` — passed: 57 files formatted, Ruff and mypy clean, 186 tests
  passed with 76% coverage, installer dry-run changed no files, wheel build/archive verification
  passed, and `dist/maldroid-0.1.0-py3-none-any.whl` was produced (SHA-256
  `87d7fe6ed4ff20afef2a3ea9e37a631f96d1337c3d1a9294a976ce30f13d62e1`).
- Remote macOS/Kali verification follows the atomic push because CI cannot run against an unpushed
  commit; the GitHub run is reported in the final delivery for this task.

## Known limitations

- No real GGUF generation, prompt-cache timing, Hebrew answer, Ghidra connector, or physical macOS
  browser acceptance ran here. `PLATFORM-011` must perform those tests for at least one hour per
  React Native and Native/Ghidra case.
- Starlette 1.3 emits one development-only warning that its `TestClient` will migrate from `httpx`
  to `httpx2`; production Web dependencies and behavior are unaffected.
- The in-app browser-control screenshot/viewport service was unreliable during this run. Default
  geometry was measured successfully; non-default breakpoints retain automated CSS/DOM coverage but
  still require the physical browser pass in `PLATFORM-011`.

## Dirty-tree and next command

Before the atomic commit, only the `PLATFORM-013` implementation, regression tests, ADR, and required
handoff documentation are modified. After commit/push the required state is a clean
`main...origin/main`.

Exact next command after the local gate and handoff commit:

```bash
git status --short --branch && git log -5 --oneline && ./scripts/dev doctor
```

Then begin `PLATFORM-011` on the owner's configured macOS host. Do not mark physical-model acceptance
from synthetic fixtures alone.
