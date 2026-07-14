# Current Handoff

Task: `CI-001`

## Goal

Make the first public macOS and Kali GitHub Actions run pass after publishing the repository.

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

## Verification

Verified in the local isolated Python 3.12 venv:

```bash
./scripts/dev format-check
./scripts/dev lint
./scripts/dev test --cov=maldroid
PYTHON="$PWD/.venv/bin/python" ./install.sh --dry-run
```

Results: the consolidated `./scripts/dev release-check` passed. Ruff formatting and lint passed;
mypy passed for 34 source files; 42 tests passed with 67% line coverage. Project hygiene,
installer dry-run, JSON parsing tests, nested help/version/config UX, MCP protocol integration, and
wheel build/archive verification passed. The wheel is `dist/maldroid-0.1.0-py3-none-any.whl`.

## Known limitations

- Target-platform and real-model acceptance are pending.
- An external desktop MCP client has not been available in this Linux workspace for UI acceptance.
- Version-specific Blutter and multi-architecture external-tool fixtures need expansion.

## Next command

```bash
maldroid --help
```

On the authorized macOS host, install the wheel, enable completion, run `config validate`, and
continue `REL-001` with the real model and external MCP client.
