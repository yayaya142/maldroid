# Project Status

Last updated: 2026-07-14

## Completed

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
  tools. Phases are unlimited by default, with durable phase notes, original-objective recovery,
  mid-task context-threshold rollover and bounded model retries. The legacy phase-ceiling config
  value is ignored so existing installations also become unlimited automatically.
- llama.cpp responses stream into a structured accumulator for content, reasoning, tool-call
  fragments, and final token usage. The active terminal line shows live generation/context totals.
- MCP client result handling preserves structured, wrapped, and plain-text errors; case-local
  evidence registration and error-payload behavior have dedicated protocol regression coverage.

## Partial or environment-gated

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

The local synthetic suite passes. See `docs/handoffs/CURRENT.md` for exact commands and counts.

## Immediate task

Run target-platform acceptance with the authorized Gemma 4 model, then expand compatibility fixtures.
