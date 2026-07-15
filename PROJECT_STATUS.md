# Project Status

Last updated: 2026-07-15

## Completed

- `maldroid update` now performs an explicit fixed-origin shallow clone, runs non-interactive
  upgrade installation, reports the installed commit, and removes temporary source on success or
  failure. Update is excluded from active CLI/Web runtimes and restores the previous private venv
  if installation fails; all user state remains outside the replaced environment.
- A production-oriented local Web workspace now mirrors the terminal's core research surface:
  project conversations, multilingual chat and RTL messages, bounded Files, live Activity,
  Findings/TODO/Checkpoint views, direct triage/report actions, settings, and external MCP.
- CLI and Web now share one `WorkspaceRuntime`; a global lease prevents concurrent model loads,
  Web starts without loading the model, and switching cases keeps at most one active runtime.
- The Web API is fixed to loopback and protected by a per-run browser token, HTTP-only SameSite
  cookie, Trusted Host checks, CSP, no-store responses, and shared `PathPolicy` file access.

- Long-investigation platform upgrade: state schema v2 separates typed semantic Checkpoints from
  research Notes, rejects operational tool/error dumps from model Notes, migrates v1 cases, adds
  complete paginated MCP readback, and deterministically builds `reports/RESEARCH_REPORT.md`.
- Working-context retention now reserves response capacity, retains only a configurable recent
  result/reasoning window, replaces older payloads with session-backed receipts, and stops repeating
  the original objective at every autonomous phase.
- The interactive workspace adds `/dashboard`, `/inventory`, `/indicators`, `/triage`, Finding
  drill-down, `/timeline`, and `/report`, plus checkpoint-aware status and toolbar views.
- React Native and Native/Ghidra now have automatically routed, evidence-oriented methodology
  playbooks. New profile tools map bundle behavior to Metro modules, inventory bridges, parse ELF
  dependencies/relocations/JNI surfaces, and summarize hardening.
- Core static triage now provides artifact inventory, network-indicator extraction, multi-family
  behavior search, and bounded byte-range hex/ASCII reads for huge or binary artifacts. Behavior
  search uses ripgrep when available and a timeout-bounded streaming fallback otherwise.

- Governance, sequential-agent handoff contract, automatic development venv, packaging, and CI.
- Validated secure configuration with the supplied Gemma 4 performance preset.
- Managed and existing-directory cases, evidence symlink/copy, registry, resume, and case listing.
- Persistent findings, notes, TODOs, sessions, summaries, and schema versions.
- Secure llama-server command construction, port policy, optional per-run API authentication,
  logging, health, and shutdown lifecycle. Authentication is off by default on loopback.
- Local normalized model client, reasoning-content preservation, bounded tool loop, and line chat.
- Core tool registry/dispatcher, path enforcement, audit, truncation, large-text FTS5, and knowledge.
- Loopback MCP Streamable HTTP discovery and execution for all tools, standalone serving, fixed-port
  reporting, active-profile filtering, and internal chat routing through the official client. Port
  8765 is stable by default and collisions fail without fallback.
- React Native inspection, Metro module indexing, bounded module reads, symbol search, and URLs.
- Static Native, Flutter, Unity, Cordova, and Cocos handlers with allowlisted adapters, artifact
  detection, bounded search/read operations, and explicit unsupported-format reporting.
- macOS/Kali installer design, safe uninstaller, starter documentation, and synthetic tests.
- Complete CLI discovery and automation surface: nested help, version/completion, explained config
  tables, get/set/reset/validate/path, consistent JSON output, MCP connector generation, and a
  reproducible wheel/release-check workflow.
- Public distribution metadata targets `yayaya142/maldroid`; local defaults do not expose a macOS
  account name.
- Loopback model health checks use direct HTTP connections without proxy routing; CLI help
  assertions are portable across ANSI behavior on Linux and macOS.
- GitHub macOS CI now uses the declared setup-python 3.12 runtime deterministically; Kali uses its
  rolling distribution Python.
- Cross-platform process lifecycle tests launch their fake server with pytest's exact interpreter,
  avoiding runner-specific `env python3` resolution.
- GitHub Actions uses macOS 26 explicitly so the tested environment matches the current target
  release and future OS upgrades remain deliberate.
- Process termination and direct loopback health behavior have independent deterministic tests;
  neither test depends on nested listener availability in hosted CI.
- GitHub Actions passes on macOS 26 with Python 3.12 and Kali rolling, including lint, formatting,
  the complete test suite, and installer dry-run.
- The installer uses an isolated, deterministic package index and cannot be redirected by ambient
  user `pip` configuration; private mirrors require an explicit MalDroid-specific override.
- Built-in chat and the ready-to-paste `SYSTEM_PROMPT.md` share the same tested, case-aware system
  prompt for MCP file workflows and evidence handling.
- Installation and `config init` provide an explained first-use workflow, automatic server
  detection, preserved reinstallation settings, and explicit local-access choices.
- API-key setup uses disabled-positive `[Y/n]` wording, and interactive server status exposes the
  active per-run key only when the user has explicitly enabled authentication.
- Owner-controlled llama.cpp WebUI, MCP proxy, and all built-in host tools are enabled by default on
  loopback. They are explicitly documented as outside MalDroid case path and audit policy.
- The managed MCP server accepts only the active local llama.cpp WebUI origins and supplies complete
  CORS preflight/response handling, so the normal one-command workflow connects at `/mcp` without a
  second terminal.
- Terminal-close, interrupt, and termination signals now stop both the MCP listener and the complete
  llama-server process group; normal interpreter exit has an additional cleanup hook.
- Every exposed managed MCP tool is namespaced with the `MalDroid_` prefix across discovery,
  execution, prompts, audit records, CLI inventory, and documentation.
- Meaningful investigation turns now require a durable note/finding checkpoint. The agent prompts
  once, then saves the ignored draft automatically through MCP so continuity does not depend on
  local-model discipline.
- Context automatically compacts at configurable 72% usage, with deterministic recovery from
  findings, recent notes, open TODOs, profile, and prior summary if model summarization fails.
- Interactive chat now provides persistent case-local history, completion, multiline editing,
  keyboard controls, rendered Markdown, live model/MCP activity, timing, context-used/remaining
  estimates, and structured status, context, history, checkpoint, server, and MCP views.
- Reasoning effort is controllable live through `/reasoning`, defaults to `medium`, appears in the
  toolbar/status, persists through `llama.reasoning_level`, and uses llama.cpp's native dynamic
  `thinking_budget_tokens` request field without requiring a server restart.
- Long requests use autonomous checkpoint/compact/continue phases instead of stopping after eight
  tools. Phases are unlimited by default, with typed semantic checkpoints, original-objective recovery,
  mid-task context-threshold rollover and bounded model retries. The legacy phase-ceiling config
  value is ignored so existing installations also become unlimited automatically.
- llama.cpp responses stream into a structured accumulator for content, reasoning, tool-call
  fragments, and final token usage. The active terminal line shows live generation/context totals.
- MCP client result handling preserves structured, wrapped, and plain-text errors; case-local
  evidence registration and error-payload behavior have dedicated protocol regression coverage.
- Profile mode is automatic by default. A bounded detector handles direct files, extracted trees,
  registered roots, and Android/ZIP archive entries; it records confidence, scores, indicators, and
  truncation, then persists changes and refreshes active MCP schemas before the next model call.
- Ambiguous profile selection can be completed by the model through validated MCP detection and
  selection tools. Manual CLI/slash overrides lock the session until `/profile auto` is requested.
- Tool-round windows no longer compact usable context. They save bounded, evidence-rich progress
  checkpoints and continue; only actual context pressure triggers summarization and reset.
- The controller actively drives TODO and Finding maintenance during substantive work. A typed
  semantic checkpoint must follow later evidence operations; operational tool/error content is
  excluded from Notes and low-value fallback content is skipped.
- Persistent external MCP connectors support loopback Streamable HTTP and SSE URLs, optional
  nicknames, namespaced discovery/execution inside the agent, non-blocking offline behavior,
  connector and case histories, bounded outputs, and explicit remove/uninstall lifecycle.

## Partial or environment-gated

- The platform upgrade passes synthetic/local contracts but still requires a multi-hour real Gemma
  4 investigation on the owner's React Native and Native/Ghidra cases. CLI latency and checkpoint
  quality under real MCP/Ghidra output are not yet physically accepted.
- Internal model subagents remain deliberately deferred. Typed state and context pruning address the
  immediate pollution problem without adding another model/state-merging security boundary.

- The reproduced Finding contract failure is fixed: evidence descriptions now have a safe default,
  validation errors identify the failing field, and `FINDINGS.md` includes evidence, tags,
  timestamps, and tool provenance. The owner's real macOS case still needs confirmation.
- Finding, Note, TODO, and Checkpoint writes roll canonical state back if deterministic Markdown
  rendering fails. Mutations still lack revision/idempotency semantics.
- `maldroid cases` opens the configured directory; `--list` and `--json` provide inventories.
- Safe Python decoding-script execution is requested but not designed or implemented. No sandbox
  claim is authorized until an ADR and adversarial OS-isolation tests exist.
- Real Gemma 4 tool-call verification requires the supplied macOS model and local llama-server.
- A physical Apple Silicon smoke test remains pending; hosted macOS 26 is the current CI target.
- External MCP discovery and reconnection at the fixed endpoint pass in the user's macOS llama.cpp
  WebUI after the browser-origin fix.
- Installer dry-run passes in hosted macOS and Kali; real install/uninstall smoke tests remain
  required on the user's target machines.

## Missing later gates

- Full compatibility fixture matrix for version-dependent third-party static tools.
- A release tag after target-platform and real-model acceptance.

## Current test status

The local 122-test suite and release gate pass with 71% coverage. GitHub Actions run `29433912079`
passes the self-update commit on macOS 26 and Kali, including dependency bootstrap, lint, mypy,
formatting, all tests, coverage, and installer dry-run. See
`docs/handoffs/CURRENT.md` for exact commands and environment-gated acceptance work.

## Immediate task

Run Web/CLI parity acceptance on the owner's macOS host, then execute one long React Native case and
one Native/Ghidra MCP case. Verify RTL chat, project switching, file preview, semantic checkpoints,
report quality, context receipts, direct triage commands, and MCP connectors against real calls.
