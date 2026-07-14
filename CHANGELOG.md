# Changelog

## 0.1.0 - Unreleased

- Fixed `MalDroid_save_finding` for natural evidence payloads that omit the optional description,
  added rollback across canonical state and Markdown views, and rendered Finding evidence, tags,
  timestamps, and tool provenance.
- Changed `maldroid cases` to open the configured cases directory by default while preserving the
  case table as `maldroid cases --list` and stable JSON output as `--json`.
- Added a reliability/research-platform master plan for the next sequential agents, including the
  observed Finding/state defects, 15 gated workstreams, extensive tool/playbook backlog, safe Python
  execution design requirements, CLI improvements, acceptance criteria, and mandatory Git/handoff
  procedure. This is planning only; the reported persistence defects remain open.
- Added secure local llama-server lifecycle using the authorized Gemma 4 performance settings.
- Enabled the owner-controlled llama.cpp WebUI, MCP proxy, and built-in host tools while keeping
  agent mode disabled and MalDroid-managed tools on the separate case-scoped MCP path.
- Added case/evidence management, persistent investigation state, sessions, and line chat.
- Added validated core tool calling, large-file contentless FTS5, local knowledge, and React Native
  Metro tooling.
- Added static Native, Flutter, Unity, Cordova, and Cocos profile tools with bounded adapters and
  explicit compatibility reporting.
- Added automatic venv development workflow, macOS/Kali installer, safe uninstaller, documentation,
  starter playbooks, and synthetic test coverage.
- Added a loopback-only MCP Streamable HTTP server for every MalDroid tool, dynamic port reporting,
  standalone `maldroid mcp serve`, official MCP client routing for chat tools, and protocol tests.
- Made MCP port 8765 fixed by default; occupied ports now fail instead of silently falling back.
- Added a polished CLI command hierarchy, nested help, version and shell completion, documented
  configuration discovery/reset/validation, JSON automation output, MCP client-config generation,
  and reproducible wheel/release-check commands.
- Prepared public GitHub distribution metadata and replaced the user-specific model prefix with an
  equivalent home-relative default.
- Fixed cross-platform CI by normalizing ANSI help output in tests and using direct loopback HTTP
  connections that cannot inherit proxy routing.
- Pinned the macOS bootstrap to the Python 3.12 runtime selected by GitHub Actions instead of an
  unrelated preinstalled Homebrew interpreter, and upgraded Actions to their Node 24 releases.
- Made the fake llama-server integration fixture use pytest's exact Python interpreter so process
  lifecycle tests do not depend on the macOS runner's shell PATH.
- Pinned CI to macOS 26 explicitly so the tested environment matches the current target macOS
  release without depending on the moving `macos-latest` label.
- Split process lifecycle and health-probe tests so macOS CI verifies both behaviors without relying
  on a nested test listener that runner networking can stall.
- Validated the complete GitHub Actions pipeline on macOS and Kali rolling.
- Made installation independent of inherited user `pip` indexes by using isolated public PyPI by
  default, with an explicit `MALDROID_PIP_INDEX_URL` override for approved private mirrors.
- Added a concise, documented system prompt with deterministic case startup, bounded file handling,
  MCP-only tool use, evidence safety, and persistent investigation guidance.
- Made llama.cpp model API authentication optional and disabled by default for direct local server
  clients, while preserving random per-run keys as an explicit setting.
- Reworked installation and first-use configuration into an explained five-step flow with automatic
  llama-server detection, Enter-to-accept defaults, quieter dependency output, and clearer next
  commands.
- Reworded setup as `Keep API-key authentication disabled? [Y/n]` and exposed the active random key
  through `/status` and `/server` only when authentication is enabled.
- Added explicit defaults for `--ui --ui-mcp-proxy --tools all`, with doctor warnings that built-in
  shell and file operations run outside MalDroid case policy.
- Fixed llama.cpp WebUI MCP connections by allowing only the managed loopback WebUI origins through
  MCP DNS-rebinding checks and adding standards-compliant CORS preflight/response headers.
- Added orderly `SIGHUP`, `SIGINT`, and `SIGTERM` cleanup plus an interpreter-exit safeguard so
  terminal closure does not leave llama-server process groups or MCP listeners behind.
- Namespaced every managed MCP tool with the `MalDroid_` prefix for clear discovery alongside tools
  from other connected MCP servers.
- Added enforced progress checkpointing after meaningful investigation work: the model must save a
  note or finding, and ignored checkpoint requests fall back to an automatic audited note.
- Added configurable automatic context compaction at 72% usage and a deterministic durable-state
  summary fallback when the local model cannot summarize an exhausted context.
- Rebuilt interactive chat as a polished terminal workspace with persistent history, slash/profile
  completion, multiline editing, keyboard shortcuts, Markdown rendering, a live context-remaining
  toolbar, visible MCP tool activity, response timing, structured status views, checkpoints, and a
  non-TTY fallback.
- Added live reasoning control with `off`, `low`, `medium`, `high`, and `unlimited` levels, a
  balanced `medium` default, native per-request llama.cpp thinking budgets, toolbar/status display,
  slash completion, persistent configuration, and audited session changes.
- Replaced the eight-round terminal stop with an autonomous multi-phase controller that saves MCP
  checkpoints, compacts context, restores the original objective, and continues through unlimited
  phases by default; context-threshold rollover also occurs inside active tasks and transient model
  requests retry with bounded backoff without terminating the CLI.
- Removed enforcement of the legacy phase ceiling, including for existing configurations that had
  persisted the former value of 16; long tasks now stop only on completion, user interruption, or a
  genuine external dependency.
- Added automatic evidence-backed profile selection across React Native, Flutter, Unity, Cordova,
  Cocos, Native, and Generic using bounded recursive inventory, archive entries, ELF magic, content
  samples, scored indicators, confidence, and mixed-framework safeguards.
- Added core `MalDroid_detect_profile` and `MalDroid_select_profile` MCP tools, automatic tool-schema
  refresh, session/UI profile-change events, model-assisted ambiguous selection, and `/profile auto`
  with manual override locking.
- Added streamed reasoning/content/tool-call reconstruction and live in-progress telemetry for
  generated tokens, context consumption, time, phase, tools, errors, and estimated capacity left.
- Hardened MCP result normalization so structured, wrapped, and plain-text error responses preserve
  the actual tool failure instead of degrading to “MCP returned no ToolResult payload.”
- Fixed repeated compaction during long investigations by decoupling tool-window checkpoints from
  context pressure; automatic compaction now runs only when the configured usage threshold is met.
- Strengthened durable investigation state: the controller prompts for active TODO/Finding
  maintenance, requires a fresh synthesis note after later evidence work, and makes automatic phase
  notes preserve bounded inputs/results, structured state, conclusions, and next actions instead of
  only listing executed tools.
- Added persistent external MCP connectors with one-command URL registration, optional nicknames,
  automatic Streamable HTTP/SSE selection, collision-safe tool namespaces, startup discovery,
  graceful unavailable-server handling, CLI health/history management, case execution audit, and
  output limiting. Connector configuration survives normal uninstall unless explicitly removed.
