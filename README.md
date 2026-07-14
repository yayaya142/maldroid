# MalDroid

MalDroid is a local, static-analysis assistant for Android malware research. It manages
investigation cases, starts one local `llama-server`, exposes a profile-specific tool set through
a local Python MCP server, and persists evidence-backed findings. Investigation data is never sent
to a cloud model.

MalDroid is not an automatic APK scanner, malware sandbox, dynamic-analysis system, or arbitrary
shell agent. It does not run APKs, DEX files, native libraries, scripts, ADB, Frida, or emulators.

## Supported systems and profiles

V1 supports macOS and Kali Linux with Python 3.11–3.14. Profiles are available for `generic`,
`react-native`, `native`, `flutter`, `unity`, `cordova`, and `cocos`. Version-sensitive external
adapters remain explicit and report compatibility limitations rather than assuming support.

## Installation

```bash
git clone https://github.com/yayaya142/maldroid.git
cd maldroid
./install.sh
```

The installer creates `~/.local/share/maldroid/venv`, installs MalDroid there, and creates
`~/.local/bin/maldroid`. It never installs Python packages into the system interpreter. Preview
all actions with `./install.sh --dry-run`. Installation uses public PyPI in isolated mode, so an
unrelated global or corporate `pip` configuration cannot redirect MalDroid dependencies. An
approved private mirror can be selected explicitly:

```bash
MALDROID_PIP_INDEX_URL="https://packages.example/simple" ./install.sh
```

The installer presents five explained steps, detects `llama-server` when it is already in `PATH`,
and shows defaults that can be accepted with Enter. Existing configuration is preserved on
reinstallation.

After installation, enable native shell completion and inspect the command map:

```bash
maldroid --install-completion
maldroid --version
maldroid --help
maldroid help mcp serve
```

The first-use setup requests the local `llama-server` and GGUF paths. The supplied macOS default
model is:

```text
~/Desktop/Tools/Ai Models/gemma-4-12B-it-qat-q4_0.gguf
```

Validate model tool calling before research use:

```bash
maldroid doctor --show-command
maldroid doctor --model-tool-test
```

The built-in chat supplies its system prompt automatically. [`SYSTEM_PROMPT.md`](SYSTEM_PROMPT.md)
contains the same short prompt in a ready-to-paste form for direct llama.cpp or external MCP client
sessions.

## Daily use

```bash
maldroid
maldroid new CASE_NAME
maldroid /path/to/investigation
maldroid /path/to/index.android.bundle --profile react-native
maldroid /path/to/artifact --copy
maldroid /path/to/artifact --mcp-port 8765
maldroid resume
maldroid cases
```

Opening an existing directory creates only `.maldroid/` initially. Opening a file creates a
managed case and registers a symlink by default. No analysis starts merely because an artifact is
detected.

The terminal workspace provides persistent input history, slash-command and profile completion,
multiline input, rendered Markdown, live model/tool activity, elapsed time, and a bottom status bar
with estimated context remaining, findings, TODOs, notes, and the active profile. Use Enter to send,
Alt+Enter for a newline, Tab to complete, arrow keys for history, Ctrl+L to redraw, and Ctrl+D to
exit. `/help` is the complete command index; `/context`, `/checkpoints`, `/history`, `/mcp`, and
`/shortcuts` expose the most useful live views. Reasoning defaults to `medium`; `/reasoning` shows
all levels and `/reasoning high` changes the budget immediately without restarting llama-server.

Long investigations run through an autonomous phase controller. Every configured tool-round window
creates a durable checkpoint, compacts context, and continues the same objective without returning
to the prompt. Phases are unlimited, with three automatic retries for transient
model-server failures. If context reaches its compaction threshold in the middle of a phase, the
same checkpoint/compact/continue sequence runs immediately. During streaming generation, the
active status line shows elapsed time, generated tokens, context consumption, and estimated tokens
remaining.

MalDroid does not rely on the local model to remember progress voluntarily. After meaningful tool
use, the agent requires a durable `MalDroid_save_note` or finding checkpoint before accepting the
final answer. If the model ignores that instruction, its draft is saved automatically as a progress
note. Context is compacted automatically at 72% usage by default, with durable case state used as a
fallback if model summarization fails.

## MCP tools

Every normal interactive run starts a loopback-only MCP Streamable HTTP server and prints its exact
endpoint and selected port. The model-side tool executor connects to this endpoint through the
official MCP client; it does not bypass MCP. To expose a case without starting the model chat:

```bash
maldroid mcp serve /path/to/case
maldroid mcp serve /path/to/case --port 8765
maldroid mcp serve /path/to/case --json
```

Connect an MCP client to the printed URL, normally `http://127.0.0.1:8765/mcp`. A typical client
entry is:

```json
{
  "mcpServers": {
    "maldroid": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

The normal `maldroid` command starts this MCP server in the background inside the same Python
process; a second terminal is not required. The endpoint uses modern MCP Streamable HTTP, so its
path is `/mcp`, not the legacy SSE path `/sse`. MalDroid permits browser requests only from the
active loopback llama.cpp WebUI port and includes the required CORS response headers. The WebUI may
connect directly or through its per-connection `Use llama-server proxy` option.

Every managed tool name starts with `MalDroid_`, for example `MalDroid_read_case_state` and
`MalDroid_search_text`. This keeps MalDroid tools recognizable when the WebUI connects several MCP
servers at once.

The MCP port is fixed. Its default is 8765, and MalDroid fails clearly if it is occupied rather
than silently changing the endpoint. Set another persistent fixed port once with
`maldroid config set mcp.preferred_port PORT`; `--port` on `mcp serve` and `--mcp-port` on normal
chat are one-run overrides. Tool discovery always returns only core
tools plus the case's active profile. The endpoint is intentionally not exposed beyond loopback;
any local client connected to it can invoke case-scoped tools until the server stops.

## Configuration

Configuration is stored at `~/.config/maldroid/config.toml`:

```bash
maldroid config init
maldroid config show
maldroid config show --json
maldroid config get mcp.preferred_port
maldroid config set llama.temperature 0.1
maldroid config set llama.reasoning_level high
maldroid config set llama.api_key_enabled true
maldroid config set limits.auto_compact_ratio 0.72
maldroid config validate
maldroid config reset llama.temperature --yes
maldroid config path
```

`config show` groups every effective value by section, marks it as default or custom, and explains
its purpose. Setters validate the complete configuration before performing an atomic save. Generate
a ready-to-paste connector definition with `maldroid mcp client-config`.

CLI options override configuration for one run. The preferred model port is 7575 and may fall back
when configured as a default. The MCP port is fixed at 8765 by default and never falls back.

The loopback llama.cpp API does not require an API key by default, which keeps direct local UIs and
clients simple. Enable `llama.api_key_enabled` only when local model API authentication is needed;
MalDroid then creates a new random key on every server start. `/status` and `/server` show the key
for the active process. Treat it as a secret. The model host remains loopback-only.

The llama.cpp WebUI, experimental MCP proxy, and `--tools all` are enabled by default for the local
owner-controlled workflow. WebUI built-in tools include shell execution and unrestricted host file
access; they are not case-scoped or audited by MalDroid. The separate MalDroid MCP tools at
`http://127.0.0.1:8765/mcp` retain profile, path, output, and audit enforcement. Both servers remain
loopback-only, and `--agent` stays forbidden.

## Evidence, findings, and large files

Evidence is registered by symlink or copy and is never overwritten. The assistant reads bounded
line ranges, uses exact or regex search, and stores oversized results under `tool-output/`. The
large-text index stores chunk boundaries and a contentless FTS5 token index; it does not store a
second readable copy of the source.

Findings, TODOs, notes, session events, and summaries survive exit and resume. Every code-based
finding should identify the case path, line or offset range, tool, and confidence.

## Knowledge

```bash
maldroid knowledge add ./playbook.md --profile react-native --copy
maldroid knowledge list
maldroid knowledge reindex
```

Built-in, user, and case playbooks are indexed locally with SQLite FTS5. Only bounded matching
excerpts enter model context.

## Troubleshooting

- `llama-server was not found`: run `maldroid config init` and provide its absolute path.
- Model missing: update `llama.model`; paths with spaces are supported.
- Tool call returned as prose: run `maldroid doctor --model-tool-test` and configure a compatible
  Jinja chat template.
- Server startup failure: inspect `<case>/.maldroid/logs/llama-server.stderr.log`.
- MCP port unavailable: stop the process already using it, or persist another fixed value with
  `maldroid config set mcp.preferred_port PORT` and update the MCP client once.
- WebUI MCP `Failed to fetch`: use the exact URL `http://127.0.0.1:8765/mcp`, confirm the normal
  MalDroid session is still open, and reinstall or upgrade MalDroid if the browser-origin fix is
  not present. `/sse` is only for legacy MCP servers.
- Python venv unavailable on Kali: install `python3-full` and `python3-venv`.

Use `--debug` only when a traceback is needed. Closing the terminal, pressing Ctrl-C, sending
SIGTERM, or using `/exit` shuts down the MCP listener and the entire managed llama-server process
group. A forceful `kill -9` cannot be handled by any application. Uninstall safely with
`./uninstall.sh`; cases and user knowledge are retained by default.

## Distribution

Maintainers can run the complete local release gate and build an installable wheel without manually
activating Python:

```bash
./scripts/dev release-check
./scripts/dev build
```

The wheel is written under `dist/` and can be installed into any supported isolated environment
with `python3 -m pip install /path/to/maldroid-0.1.0-py3-none-any.whl`. See
[`docs/CLI.md`](docs/CLI.md) for the command and automation-output reference.
