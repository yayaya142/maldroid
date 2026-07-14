# Current Handoff

Task: `CLI-001`

## Goal

Make the complete CLI discoverable, consistent, automation-friendly, and straightforward to
package and distribute.

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
