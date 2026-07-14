# Current Handoff

Task: `MCP-002`

## Goal

Expose every MalDroid tool through a connectable local MCP server and route built-in chat tool
execution through it.

## State

- `maldroid mcp serve [CASE]` starts an official MCP Streamable HTTP endpoint and prints its port.
- MCP port 8765 is fixed by default; a collision fails instead of changing saved client settings.
- Normal chat starts the same server and executes model tool calls through its official MCP client.
- Active-profile discovery, Pydantic validation, path policy, output limits, audit, and serialized
  execution remain enforced by the existing registry and dispatcher.
- Authorized model/server integration is environment-gated because this workspace lacks both the
  macOS GGUF path and `llama-server`.

## Verification

Verified in the local isolated Python 3.12 venv:

```bash
./scripts/dev format-check
./scripts/dev lint
./scripts/dev test --cov=maldroid
PYTHON="$PWD/.venv/bin/python" ./install.sh --dry-run
```

Results: Ruff formatting and lint passed; mypy passed for 34 source files; 37 tests passed with 66%
line coverage. The focused MCP tests use the official client to initialize, list tools, execute a
tool, complete an agent/model round trip, observe a profile change, and reject a busy configured
port without fallback. Project hygiene, installer dry-run, `doctor`, MCP CLI
help, and wheel build also passed.

## Known limitations

- Target-platform and real-model acceptance are pending.
- An external desktop MCP client has not been available in this Linux workspace for UI acceptance.
- Version-specific Blutter and multi-architecture external-tool fixtures need expansion.

## Next command

```bash
maldroid mcp serve /path/to/case --json
```

Copy the reported endpoint into the chosen MCP client, then list tools and call `read_case_state`.
