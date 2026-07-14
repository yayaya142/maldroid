# CLI Reference

MalDroid is designed for both interactive terminal use and predictable local automation. Human
output uses Rich tables; commands that expose structured state provide `--json`.

## Discovery and completion

```bash
maldroid --help
maldroid help config
maldroid help mcp serve
maldroid --version
maldroid --install-completion
maldroid --show-completion
```

Both `-h` and `--help` work. `maldroid help` accepts nested command names. With no arguments,
MalDroid preserves the daily workflow and opens a new case.

## Daily workflow

```bash
maldroid new NAME --profile generic
maldroid open /path/to/case
maldroid open /path/to/artifact --copy --profile react-native
maldroid resume
maldroid cases
maldroid cases --json
```

The shorthand `maldroid /path/to/artifact` is equivalent to `maldroid open /path/to/artifact`.
`--port` changes the model port for one run; `--mcp-port` changes the fixed MCP port for one run.

## Configuration

```bash
maldroid config init
maldroid config show
maldroid config show --json
maldroid config get llama.model
maldroid config get llama.api_key_enabled
maldroid config set llama.api_key_enabled true
maldroid config get mcp.preferred_port --json
maldroid config set mcp.preferred_port 8765
maldroid config reset mcp.preferred_port --yes
maldroid config validate
maldroid config path
```

Keys use `section.key` form. Unknown keys, invalid types, unsafe llama.cpp flags, non-loopback hosts,
and invalid cross-field limits are rejected before the file is replaced. `config reset` changes one
key only. The configuration file is private-mode TOML and saves atomically.

`llama.api_key_enabled` defaults to `false` for uncomplicated direct access to the loopback
llama.cpp UI and API. When set to `true`, each managed server start receives a new random key. The
setting does not change MCP access and cannot make the model server listen beyond loopback.

## MCP

```bash
maldroid mcp client-config
maldroid mcp client-config --name android-research
maldroid mcp serve /path/to/case
maldroid mcp serve /path/to/case --json
```

The connector URL is fixed at `http://127.0.0.1:8765/mcp` unless configuration changes it. A port
collision is an error. `client-config` prints a ready-to-paste JSON connector definition.

## Diagnostics and inventory

```bash
maldroid doctor
maldroid doctor --json
maldroid doctor --show-command
maldroid doctor --model-tool-test
maldroid profiles --json
maldroid tools --profile react-native --json
```

`doctor --show-command` redacts the random API secret whenever authentication is enabled.
`--model-tool-test` is interactive and intentionally cannot be combined with `--json`.

## Exit behavior

- Exit code `0`: command completed normally.
- Exit code `1`: validated application, configuration, case, security, server, or tool failure.
- Exit code `2`: command-line syntax or usage error.

JSON output is UTF-8 and contains no terminal color sequences. Human-readable errors are concise;
commands with `--debug` expose tracebacks for development diagnosis.
