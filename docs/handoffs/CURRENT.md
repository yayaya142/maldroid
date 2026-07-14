# Current Handoff

Task: `REL-001`

## Goal

Run target-machine acceptance with the authorized Gemma 4 model and an external MCP client.

## State

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

## Verification

Verified in the local isolated Python 3.12 venv:

```bash
./scripts/dev release-check
```

Results: the consolidated release check passed. Ruff formatting and lint passed; mypy passed for 34
source files; 57 tests passed with 70% line coverage. Project hygiene, installer dry-run, browser
MCP origin/CORS coverage, termination-signal cleanup, namespaced tool discovery, enforced and
automatic checkpoints, compaction fallback, JSON parsing tests, protocol integration, and wheel
build verification passed. The wheel is `dist/maldroid-0.1.0-py3-none-any.whl`.

## Known limitations

- Target-platform and real-model acceptance are pending.
- Browser-origin behavior is covered with an MCP handshake, CORS preflight, hostile-origin
  rejection tests, and a successful real macOS llama.cpp WebUI connection.
- Version-specific Blutter and multi-architecture external-tool fixtures need expansion.

## Next command

```bash
maldroid --help
```

On the authorized macOS host, pull and reinstall MalDroid, start a normal case, then reconnect
`http://127.0.0.1:8765/mcp` in the llama.cpp WebUI without launching `maldroid mcp serve` separately.
