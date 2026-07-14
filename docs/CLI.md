# CLI Reference

MalDroid is designed for both interactive terminal use and predictable local automation. Human
output uses Rich tables; commands that expose structured state provide `--json`.

## Interactive terminal workspace

A normal case opens a full-screen-aware terminal prompt without taking over the alternate screen.
The bottom toolbar always shows the active profile, estimated context usage and tokens remaining,
finding count, open TODO count, and durable note count. Context estimates include current messages
and active tool schemas, using conservative character-based measurement rather than exact model
tokenization.

Model waits use a live spinner. Every MCP call appears as it starts and finishes, including errors,
saved full-output paths, and truncation status. Assistant Markdown is rendered after the turn, then
a footer reports elapsed time, tool count, and context remaining. Input history is persisted inside
the case at `.maldroid/input-history`.

Keyboard controls:

- Enter sends the current message.
- Alt+Enter, or Escape followed by Enter, inserts a newline.
- Tab completes slash commands and profile names.
- Up and Down navigate persistent input history.
- Ctrl+L redraws the terminal.
- Ctrl+C cancels the current input or response; Ctrl+D exits from an empty prompt.

Use `/help` for the complete command table. The principal live views are `/status`, `/context`,
`/reasoning`, `/tools`, `/findings`, `/todo`, `/checkpoints`, `/history`, `/server`, and `/mcp`. `/quit` is an
alias for `/exit`. In non-interactive input or with `MALDROID_SIMPLE_INPUT=1`, MalDroid falls back
to its reliable line-oriented prompt.

### Reasoning control

`llama.reasoning_level` defaults to `medium`. The terminal toolbar and `/status` show the active
level. `/reasoning` lists the available levels; `/reasoning LEVEL` changes the current session
immediately, while `maldroid config set llama.reasoning_level LEVEL` changes the persisted default.

| Level | Per-request thinking budget |
| --- | ---: |
| `off` | 0 tokens |
| `low` | 512 tokens |
| `medium` | 1,536 tokens |
| `high` | 3,072 tokens |
| `unlimited` | no explicit limit |

MalDroid sends the native llama.cpp `thinking_budget_tokens` request property. It intentionally
does not set a command-line `--reasoning-budget`, because a command-line value would prevent live
per-request adjustment. Reasoning support still depends on the selected model and chat template,
and the overall `llama.max_response_tokens` limit applies to the complete generation. See the
[official llama-server reasoning options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#usage).

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
maldroid config get llama.reasoning_level
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
interactive `/status` and `/server` commands show the current key for direct local clients; treat
that output as secret. The setting does not change MCP access and cannot make the model server
listen beyond loopback.

`llama.ui_enabled`, `llama.ui_mcp_proxy_enabled`, and `llama.built_in_tools_enabled` default to
`true`. This produces `--ui --ui-mcp-proxy --tools all`. Built-in WebUI tools run with the host
permissions of llama-server and are not constrained or audited by MalDroid. Disable them with:

```bash
maldroid config set llama.built_in_tools_enabled false
```

## MCP

```bash
maldroid mcp client-config
maldroid mcp client-config --name android-research
maldroid mcp serve /path/to/case
maldroid mcp serve /path/to/case --json
```

The connector URL is fixed at `http://127.0.0.1:8765/mcp` unless configuration changes it. A port
collision is an error. `client-config` prints a ready-to-paste JSON connector definition.

Normal case commands start the MCP listener in a background thread inside the MalDroid process, so
do not run `maldroid mcp serve` in a second terminal. `/mcp` is the Streamable HTTP endpoint;
`/sse` is a legacy transport path used by some unrelated servers. Browser access is limited to the
active loopback llama.cpp WebUI origin, with direct CORS and the optional llama-server proxy both
supported.

All names returned by MCP `tools/list` and `maldroid tools` begin with `MalDroid_`. The prefix also
applies to model-generated tool calls and the local execution audit.

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

`limits.auto_compact_ratio` defaults to `0.72` and accepts values from `0.5` through `0.8`.
Automatic compaction preserves full JSONL history and builds the new context from the generated
summary or, if generation fails, durable findings, notes, TODOs, profile, and prior summary.

## Exit behavior

`/exit`, Ctrl-C, terminal-close `SIGHUP`, and `SIGTERM` all enter the same cleanup path. MalDroid
stops the MCP listener, terminates the managed llama-server process group, and escalates to a forced
group kill only when graceful shutdown times out.

- Exit code `0`: command completed normally.
- Exit code `1`: validated application, configuration, case, security, server, or tool failure.
- Exit code `2`: command-line syntax or usage error.

JSON output is UTF-8 and contains no terminal color sequences. Human-readable errors are concise;
commands with `--debug` expose tracebacks for development diagnosis.
