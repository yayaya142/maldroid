# CLI Reference

MalDroid is designed for both interactive terminal use and predictable local automation. Human
output uses Rich tables; commands that expose structured state provide `--json`.

Open the configured cases directory in Finder or the system file manager:

```bash
maldroid cases
maldroid cases --list  # show the terminal table instead
maldroid cases --json  # automation-friendly case inventory
```

## Interactive terminal workspace

Running `maldroid` without arguments now asks for `1` Web or `2` CLI. Use `maldroid server` or
`maldroid cli [PATH]` to select a surface directly. A global runtime lease prevents Web and CLI
from loading the model at the same time. Complete Web usage is documented in
[`WEB.md`](WEB.md).

A normal case opens a full-screen-aware terminal prompt without taking over the alternate screen.
The bottom toolbar always shows the active profile, estimated context usage and tokens remaining,
finding count, open TODO count, and durable note count. Context estimates include current messages
and active tool schemas, using conservative character-based measurement rather than exact model
tokenization.

Model waits use a live spinner. Every MCP call appears as it starts and finishes, including errors,
saved full-output paths, and truncation status. Assistant Markdown is rendered after the turn, then
a footer reports elapsed time, phase and tool counts, recovered errors, generated tokens, and
context remaining. During streamed reasoning and response generation, the active bottom line
updates continuously with elapsed time, approximate output tokens, total context consumption, and
estimated tokens remaining. Exact completion usage is used when llama.cpp supplies it; otherwise
the display is explicitly approximate. Input history is persisted inside the case at
`.maldroid/input-history`.

### Long-running agent controller

A user request is not stopped merely because one tool window is exhausted. The default controller
runs eight tool rounds per phase, writes a typed semantic MCP checkpoint, and continues without
compacting usable context. Phases are unlimited by default, allowing a task to run for as long as
completion requires. Compaction happens only when context reaches the
configured compaction threshold, so context exhaustion is handled inside the active task rather
than after it returns to the prompt. The legacy `limits.max_task_phases` key remains accepted for
configuration compatibility but no longer stops the controller, including in existing installs
that previously saved the old value of `16`.

Transient model-request failures are retried three times with bounded backoff. Individual tool
errors are returned to the model so it can correct arguments or choose a safe alternative. MCP
error responses are normalized from structured, wrapped, and plain-text result variants, avoiding
the unhelpful generic “no ToolResult payload” failure when the server supplied an error message.
If all retries fail, the turn pauses with a clear external-dependency panel while the CLI and case
remain open; it does not terminate the session or discard durable work.

Mechanical repeated-output loops are handled separately from connection retries. The streaming
guard stops the response, preserves only detection metadata, opens a fresh append-only session with
durable state and bounded recent tool results, and continues the same objective. Recovery is capped
at two fresh sessions per turn. It defaults on and can be changed persistently with:

```bash
maldroid config set llama.repetition_recovery_enabled false
maldroid config reset llama.repetition_recovery_enabled
```

The controller reserves the next completion budget in its context calculation. By default only the
six most recent tool results and reasoning blocks remain in full active context; older results are
replaced with small receipts while complete session JSONL and saved output remain available. The
original objective is not reinserted at every tool window.

Controller settings are validated and discoverable:

```bash
maldroid config get limits.max_tool_rounds
maldroid config get limits.max_task_phases
maldroid config get limits.model_retry_attempts
```

### Automatic profile selection

Normal runs start in `auto` profile mode. Before the first model request and at the start of later
turns, MalDroid performs a bounded static inventory. It scores exact framework filenames and paths,
APK/AAB/APKS/ZIP entry names without extracting them, ELF headers, and bounded JavaScript samples.
The strongest actionable result activates its profile and refreshes the model's tool schemas before
the next request.

React Native, Flutter, Unity, Cordova, Cocos, and Native indicators are scored independently. A
deterministic framework priority resolves ties, while Native scoring is capped so common `.so`
dependencies do not hide stronger framework evidence. Generic remains active when confidence is
insufficient. Detection scans at most 20,000 files/archive entries and 64 bounded content samples.

The always-available `MalDroid_detect_profile` tool returns scores, confidence, indicators, scan
counts, and truncation status. When deterministic evidence remains ambiguous, the model may call
`MalDroid_select_profile` with a validated profile, confidence, and concrete reason. The controller
applies the recommendation and refreshes active tools. The model is explicitly instructed not to
ask the user to identify frameworks.

```text
/profile            # show current mode and profiles
/profile native     # force a manual override for this session
/profile auto       # resume automatic detection and adaptation
```

An explicit `--profile` CLI option starts that run in manual mode. Automatic switching never
overrides a manual session choice.

### Persistent external MCP connectors

Add a local Streamable HTTP or SSE server by pasting its URL. A nickname is optional:

```bash
maldroid mcp add http://127.0.0.1:8080/mcp --name ghidra
maldroid mcp add http://localhost:9000/sse
maldroid mcp list [--json]
maldroid mcp test NAME
maldroid mcp history [--json]
maldroid mcp remove NAME [--yes]
```

Transport is inferred from `/mcp` or `/sse`. The default name is `local-PORT`; exposed model tools
use `MCP_<nickname>_` names. Saved servers are discovered at normal chat startup. Connections and
tool calls appear in session history, while the persistent connector audit records adds, removals,
tests, and connection attempts. Restart MalDroid after adding a connector to make its tools
available to the active model session.

Only loopback URLs without embedded credentials, queries, or fragments are accepted. External MCP
implementations are independent programs: MalDroid limits returned output and records invocation
status, but cannot apply case path policy or constrain their side effects. `/tools` shows connected
external tools and `/mcp` shows connector health.

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

Direct research commands:

```text
/dashboard
/inventory [PATH]
/indicators [PATH]
/triage [PATH]
/findings [FIND-ID]
/timeline [5-100]
/report
```

These commands inspect durable/local state directly without consuming a model turn. `/report`
atomically rebuilds `reports/RESEARCH_REPORT.md` from Findings, TODOs, and the latest typed
checkpoint.

`/triage` and `/indicators` use global result/time budgets even on very large repositories. Broad
scans do not follow nested symbolic links or recurse into routine internal/generated trees; an
explicit registered evidence or generated-output path remains readable. Partial results state
whether totals are exact and why the scan stopped. Search previews are centered on matches inside
minified lines, while line-range tools retain only bounded prefixes and mark shortened lines.

### Reasoning control

`llama.reasoning_level` defaults to `medium`. The terminal toolbar and `/status` show the active
level. `/reasoning` lists the available levels; `/reasoning LEVEL` changes the current session
immediately, while `maldroid config set llama.reasoning_level LEVEL` changes the persisted default.

| Level | Per-request thinking budget |
| --- | ---: |
| `off` | 0 tokens |
| `low` | 256 tokens |
| `medium` | 768 tokens |
| `high` | 1,536 tokens |
| `unlimited` | no explicit limit |

MalDroid sends the native llama.cpp `thinking_budget_tokens` request property. It intentionally
does not set a command-line `--reasoning-budget`, because a command-line value would prevent live
per-request adjustment. Reasoning support still depends on the selected model and chat template,
and the overall `llama.max_response_tokens` limit applies to the complete generation. See the
[official llama-server reasoning options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#usage).

Requests enable llama.cpp prompt caching, prompt-progress events, and SSE keepalive. The SDK retry
layer is disabled so `limits.model_retry_attempts` remains the single visible retry policy.
Three consecutive identical tool outcomes trigger a visible strategy-change instruction; five stop
the turn safely without creating a low-value Note or checkpoint. Normal shutdown persists typed
durable state deterministically and does not start a compaction generation after the user exits.
`llama.stream_idle_timeout_seconds` defaults to 120 and bounds a stream that stops producing local
network activity. If a generation ends with reasoning but no answer/tool call, MalDroid retries it
once with reasoning off and keeps the empty attempt out of conversation history.

## Discovery and completion

```bash
maldroid --help
maldroid help config
maldroid help mcp serve
maldroid --version
maldroid --install-completion
maldroid --show-completion
```

Both `-h` and `--help` work. `maldroid help` accepts nested command names. With no arguments in an
interactive terminal, MalDroid displays the Web/CLI selector. Non-TTY invocation displays help so
scripts never block on a prompt.

## Updating

```bash
maldroid update
```

The update command performs an explicit network operation against the fixed official repository,
clones only its `main` branch into a temporary directory, runs the installer in non-interactive
upgrade mode, and removes the clone on success or failure. It prints the installed short commit.
The old private venv is backed up and restored if installation fails. User configuration, cases,
knowledge, and MCP connector state are not stored in the venv and are preserved. Stop an active
CLI or Web workspace before updating.

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
Tool-window checkpoints do not trigger compaction: they preserve meaningful evidence activity and
structured state while the existing context remains available. The terminal announces when the
agent is organizing TODO/Finding state, saving a checkpoint, or compacting for actual context use.
`limits.retained_tool_results` defaults to `6` and controls how many full results remain in the
active model context; it never removes the session/audit copy.

## Exit behavior

`/exit`, Ctrl-C, terminal-close `SIGHUP`, and `SIGTERM` all enter the same cleanup path. MalDroid
stops the MCP listener, terminates the managed llama-server process group, and escalates to a forced
group kill only when graceful shutdown times out.

- Exit code `0`: command completed normally.
- Exit code `1`: validated application, configuration, case, security, server, or tool failure.
- Exit code `2`: command-line syntax or usage error.

JSON output is UTF-8 and contains no terminal color sequences. Human-readable errors are concise;
commands with `--debug` expose tracebacks for development diagnosis.
