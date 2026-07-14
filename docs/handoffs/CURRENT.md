# Current Handoff

Task: `REL-010`, `CLI-010`

## Goal

Confirm the focused Finding persistence fix on the owner's macOS case.

## State

- The owner has reprioritized the project around reliability, research depth, CLI transparency,
  case-folder navigation, and safely designed Python decoding scripts. Implementation is explicitly
  deferred to the next agent.
- `NEXT_AGENT_MASTER_PLAN.md` is now the mandatory gated backlog and Git/handoff guide. `AGENTS.md`
  requires every future agent to read it at startup.
- Natural Finding evidence no longer requires `evidence[].description`; a default is applied and
  validation errors name exact fields. Finding Markdown includes evidence, tags, timestamps, and
  tool provenance.
- Finding, Note, and TODO mutations rebuild deterministic Markdown views and roll canonical state
  back if rendering fails. Revision/idempotency and complete MCP readback remain future work.
- `maldroid cases` now opens the configured folder. `--list` and `--json` preserve inventory output.

- `maldroid mcp serve [CASE]` starts an official MCP Streamable HTTP endpoint and prints its port.
- MCP port 8765 is fixed by default; a collision fails instead of changing saved client settings.
- Normal chat starts the same server and executes model tool calls through its official MCP client.
- Active-profile discovery, Pydantic validation, path policy, output limits, audit, and serialized
  execution remain enforced by the existing registry and dispatcher.
- Authorized model/server integration is environment-gated because this workspace lacks both the
  macOS GGUF path and `llama-server`.
- Root and nested help, version, shell completion, JSON inventory/doctor output, full configuration
  discovery/reset/validation, MCP connector generation, and release build scripts are implemented.
- README and package metadata point to the real GitHub repository. The model default is home-relative
  so it resolves to the authorized path without publishing the local macOS account name.
- The initial CI failures were isolated to ANSI-decorated help output and proxy-sensitive loopback
  health probes. Tests now normalize ANSI, and production health checks use direct loopback HTTP.
- The macOS workflow now forces bootstrap to use the Python 3.12 runtime selected by setup-python;
  it no longer silently selects a preinstalled Homebrew Python 3.14.
- The process lifecycle fixture now invokes its fake server with pytest's exact interpreter rather
  than resolving `python3` through the macOS runner PATH.
- The workflow targets `macos-26` explicitly to match the user's current macOS release; future OS
  image upgrades must be deliberate compatibility tasks.
- Process lifecycle and direct loopback health checks are tested independently to avoid hosted
  macOS nested-listener stalls while retaining assertions for the exact health endpoint.
- Public GitHub Actions run `29320731148` passed on macOS 26/Python 3.12 and Kali rolling, including
  lint, format checks, all tests, and installer dry-run.
- Installation now uses public PyPI through pip isolated mode by default, preventing inherited
  global indexes from breaking build dependency resolution. Approved private mirrors require the
  explicit `MALDROID_PIP_INDEX_URL` override.
- `SYSTEM_PROMPT.md` mirrors the tested built-in system prompt and is ready to paste into direct
  llama.cpp or external MCP client sessions; it defines case startup and bounded file handling.
- llama.cpp model API authentication is optional and disabled by default for direct local UI/API
  use. `llama.api_key_enabled=true` restores a redacted random key per managed server run.
- Installation and `config init` now use a five-step guided flow with detected paths, explained
  defaults, quiet package installation, preserved existing configuration, and practical next steps.
- Setup asks `Keep API-key authentication disabled? [Y/n]`; choosing `n` enables a random key that
  the active `/status` and `/server` output exposes for local clients.
- By explicit owner decision, llama.cpp starts with `--ui --ui-mcp-proxy --tools all`. Built-in
  WebUI shell/file tools run with host permissions outside MalDroid case policy; managed chat tools
  still use the case-scoped Python MCP dispatcher.
- The user's macOS test confirmed that the normal command already owns the port 8765 listener.
  Browser initialization failed because MCP transport security allowed no `Origin` header. The
  server now allows only origins on the active loopback llama-server port and emits CORS headers;
  `/mcp` remains the correct Streamable HTTP endpoint and no second terminal is required.
- The user confirmed the updated endpoint now connects successfully in the macOS llama.cpp WebUI.
- MalDroid now handles terminal-close `SIGHUP`, Ctrl-C, and `SIGTERM` with the same orderly cleanup
  path and registers an interpreter-exit fallback for the managed llama-server process group.
- The registry centrally publishes every managed tool as `MalDroid_<tool_name>`; prompts, internal
  slash commands, tests, CLI inventory, audit events, and external MCP discovery use that prefix.
- Investigation turns cannot silently end without durable progress: the agent requests a
  `MalDroid_save_note`/finding checkpoint and automatically saves the draft when ignored.
- Context compacts automatically at `limits.auto_compact_ratio=0.72`. A failed model summary falls
  back to findings, recent notes, open TODOs, active profile, and the previous durable summary.
- Interactive chat is now a terminal workspace with persistent history, completion, multiline
  input, keyboard shortcuts, Markdown responses, live model/tool/checkpoint events, response
  timing, context remaining, and structured slash-command views. Non-TTY input retains the simple
  prompt path.
- Reasoning defaults to `medium` and can change live through `/reasoning` using llama.cpp's native
  per-request `thinking_budget_tokens`. The toolbar, welcome panel, and status view expose the active
  level; session logs record changes and persistent defaults use `llama.reasoning_level`.
- The former eight-round stop is now an autonomous phase rollover: an MCP note and compacted summary
  preserve state, the original objective is restored, and work continues without user input. The
  default is unlimited phases (`limits.max_task_phases=0`), plus three bounded retries for transient
  model failures. Context threshold crossings trigger the same rollover during an active phase.
  The prior saved value of 16 is accepted but no longer enforced, so upgrades need no manual edit.
- Local model responses stream structured content, reasoning, tool-call fragments, and usage into
  the agent. The active status line displays elapsed time, generated tokens, context usage, and
  remaining capacity while the model is working.
- MCP result parsing now accepts direct, wrapped, and text-encoded ToolResult payloads and preserves
  plain MCP errors. A real HTTP regression covers successful case-local evidence registration and
  invalid-path error propagation.
- Profile selection is automatic by default. Bounded scored detection covers filesystem/archive
  names, registered evidence, ELF magic, and content samples, with Native-score caps for mixed apps.
  Actionable changes persist, emit UI/session events, and rebuild model tool schemas immediately.
- `MalDroid_detect_profile` exposes indicators and confidence through MCP; the model can use
  `MalDroid_select_profile` with a validated evidence reason when deterministic detection is
  ambiguous. Manual choices hide model selection until `/profile auto` restores adaptation.
- Tool-window rollover no longer invokes compaction. It saves a bounded evidence-rich checkpoint
  and continues with the current context; only measured context pressure invokes summarization.
- After evidence work starts, the controller visibly requests TODO/Finding maintenance. Fresh
  evidence invalidates an older synthesis note, and automatic fallback notes preserve the
  objective, bounded arguments/results, current structured state, synthesis, and next action.
- External local MCP servers can be saved with URL plus optional nickname. Both Streamable HTTP and
  SSE are discovered at startup, namespaced into model schemas, executed through official MCP
  clients, output-limited, and audited. Registry/history survive uninstall unless configuration
  removal is explicitly approved; unavailable connectors do not block a case.

## Verification

Verified in the local isolated Python 3.12 venv:

```bash
./scripts/dev release-check
```

Results: the focused change passed Ruff formatting/lint, mypy for 36 source files, and the complete
93-test suite. The previous consolidated release check also passed. Project hygiene, installer dry-run, browser
MCP origin/CORS coverage, termination-signal cleanup, namespaced tool discovery, enforced and
automatic and phase checkpoints, autonomous continuation, model retry, compaction fallback,
streaming token/tool reconstruction, live terminal telemetry, dynamic reasoning-budget request
tests, MCP result variants, automatic and model-assisted profile selection, archive/mixed-framework
fixtures, non-compacting tool windows, meaningful checkpoint contents, structured TODO/Finding
discipline, persistent external MCP registry/history, Streamable HTTP discovery/execution,
namespace routing, SSE configuration, offline behavior, uninstall preservation, JSON parsing,
protocol integration, and wheel build verification passed. The wheel is
`dist/maldroid-0.1.0-py3-none-any.whl`.

## Known limitations

- The reproduced Finding schema/view failure is fixed; confirmation on the real macOS case remains.
- The master-plan tool, guide, CLI, agent-controller, and Python-execution work is backlog only.
- Target-platform and real-model acceptance are pending.
- Browser-origin behavior is covered with an MCP handshake, CORS preflight, hostile-origin
  rejection tests, and a successful real macOS llama.cpp WebUI connection.
- Version-specific Blutter and multi-architecture external-tool fixtures need expansion.

## Next command

```bash
./scripts/dev test
```

Then install the current commit on the owner's macOS host and retry the previously failing Finding.
If it still fails, capture the sanitized structured tool response and audit entry before changing
the implementation again.
