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

Update an installed copy without keeping a source repository:

```bash
maldroid update
```

This explicitly clones the official `main` branch into an OS temporary directory, installs it,
prints the installed commit, and removes the checkout. The prior private venv is restored if the
new installation fails. Configuration, investigations, knowledge, and MCP connectors are preserved.
Update cannot run while a CLI or Web workspace is active.

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
maldroid                         # choose Web or CLI
maldroid server                  # modern local Web workspace
maldroid server --port 8787
maldroid cli /path/to/investigation
maldroid new CASE_NAME
maldroid /path/to/investigation
maldroid /path/to/index.android.bundle --profile react-native
maldroid /path/to/artifact --copy
maldroid /path/to/artifact --mcp-port 8765
maldroid resume
maldroid cases
```

The Web workspace provides project conversations, multilingual chat with per-message RTL support,
a VS Code-style bounded file explorer and preview, live tool activity, durable research views,
settings, reports, and external MCP connector management. It stays local on `127.0.0.1`, requires
a random per-run browser token, and uses the same case runtime and path policy as the CLI. See
[`docs/WEB.md`](docs/WEB.md).

After an investigation finishes loading, use the clearly labeled message box at the bottom of the
center pane; Actions are optional direct operations, not the chat entry point. The Web workspace
supports persistent Dark and Light appearance, a searchable/collapsible file tree, and a header
restore button whenever the project sidebar is collapsed.

The layout is designed for normal 100% browser zoom: Projects and Files use fluid widths on desktop,
the chat stays centered in its remaining space, and both side panes become header-controlled drawers
on compact laptop, tablet, and phone widths instead of forcing horizontal overflow.

During long turns, a central Live Work panel confirms that the local model is active with elapsed
time, phase, tool count, approximate token telemetry, and recent operational steps. It deliberately
does not expose private model reasoning.

Use **Stop** in Live Work to cancel the active turn without restarting llama-server. MalDroid drops
partial model output while retaining completed tool results and durable research records. A tool
already in progress finishes its current safe operation before the turn closes.

Opening an existing directory creates only `.maldroid/` initially. Opening a file creates a
managed case and registers a symlink by default. No analysis starts merely because an artifact is
detected.

The terminal workspace provides persistent input history, slash-command and profile completion,
multiline input, rendered Markdown, live model/tool activity, elapsed time, and a bottom status bar
with estimated context remaining, findings, TODOs, checkpoints, and the active profile. Use Enter to send,
Alt+Enter for a newline, Tab to complete, arrow keys for history, Ctrl+L to redraw, and Ctrl+D to
exit. `/help` is the complete command index; `/context`, `/checkpoints`, `/history`, `/mcp`, and
`/shortcuts` expose the most useful live views. Reasoning defaults to `medium`; `/reasoning` shows
all levels and `/reasoning high` changes the budget immediately without restarting llama-server.

Research-oriented shortcuts avoid unnecessary model turns:

```text
/dashboard                 live objective, context, Findings, TODOs, and next action
/inventory [PATH]          file-type/size inventory and large-text candidates
/indicators [PATH]         URLs, domains, IPs, emails, and WebSockets
/triage [PATH]             high-signal behavior families in one static pass
/findings [FIND-ID]        list or expand a complete Finding
/timeline [COUNT]          concise tool/state/compaction timeline
/report                    rebuild reports/RESEARCH_REPORT.md from durable state
```

Long investigations run through an autonomous phase controller. Every configured tool-round window
creates a typed semantic checkpoint and continues the same objective without returning to the prompt or
throwing away usable context. Compaction is independent and runs only when the actual context ratio
crosses its configured threshold. Older tool payloads become small active-context receipts while
their full session/output records remain on disk. The next completion budget is reserved before
the threshold is calculated. Phases are unlimited, with three automatic retries for transient
model-server failures. During streaming generation, the active status line shows elapsed time,
generated tokens, context consumption, and estimated tokens remaining.

Runaway repeated output is detected while it streams. By default MalDroid stops the bad generation,
starts a clean append-only session, carries forward durable state and bounded recent tool results,
and continues the same request automatically. The repeated partial text is not stored as research
or returned to the model. Disable this behavior with
`maldroid config set llama.repetition_recovery_enabled false`.

Profile selection is automatic by default. MalDroid recursively inspects bounded artifact names,
archive entries, ELF magic, and small content samples, then activates React Native, Flutter, Unity,
Cordova, Cocos, Native, or Generic tools with evidence-backed confidence. Mixed apps use scored
framework indicators so incidental native libraries do not override a stronger framework match.
For ambiguous artifacts, the model can call `MalDroid_detect_profile` and make a validated
`MalDroid_select_profile` recommendation after inspecting concrete evidence. `/profile NAME` is a
manual session override; `/profile auto` restores adaptation.

MalDroid does not rely on the local model to remember progress voluntarily. It directs the model to
create and complete TODOs, turn supported facts and labeled hypotheses into evidence-backed
Findings, and save typed semantic checkpoints. Before accepting a final answer it requires fresh
continuity after the latest evidence work. If the model ignores that instruction, MalDroid keeps
only a semantic synthesis and durable IDs; tool arguments, results, and failures remain in audit
streams. Low-value fallback content is skipped rather than promoted to research. Context is
compacted automatically at 72% usage by default, with
durable case state used as a fallback if model summarization fails.

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

### Additional MCP servers

MalDroid can attach additional local MCP servers directly to its CLI agent. Paste the URL and,
optionally, give it a short nickname:

```bash
maldroid mcp add http://127.0.0.1:8080/mcp --name ghidra
maldroid mcp add http://localhost:9000/sse --name legacy
maldroid mcp list
maldroid mcp test ghidra
maldroid mcp history
maldroid mcp remove ghidra
```

The `/mcp` suffix selects Streamable HTTP and `/sse` selects legacy SSE automatically. Without
`--name`, MalDroid uses `local-PORT`. Discovered tools are namespaced as
`MCP_<nickname>_<tool-name>`, added to the model on the next MalDroid session, shown by `/tools` and
`/mcp`, and recorded in normal case tool history. An unavailable saved server produces a warning
and is retried on the next run without blocking the investigation.

Connectors and their add/remove/test/connection history live in
`~/.config/maldroid/mcp-servers.json` and `mcp-servers-history.jsonl`. A normal reinstall or
uninstall preserves them. `uninstall.sh` removes them only when the user explicitly approves the
configuration-removal prompt. URLs are restricted to loopback, cannot embed credentials or query
tokens, and may use only HTTP(S). External MCP servers have their own permissions and are not
restricted by MalDroid's case path policy; only their invocation status and returned-output limit
are enforced by MalDroid.

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

Findings, TODOs, typed checkpoints, meaningful research notes, session events, reports, and
summaries survive exit and resume. Operational failures and tool dumps stay in session/audit logs;
they are rejected from research Notes. Every code-based finding should identify the case path,
line or offset range, tool, and confidence.

## Knowledge

```bash
maldroid knowledge add ./playbook.md --profile react-native --copy
maldroid knowledge list
maldroid knowledge reindex
```

Built-in, user, and case playbooks are indexed locally with SQLite FTS5. Only bounded matching
excerpts enter model context. React Native and Native profiles automatically receive a bounded
methodology guide covering Metro/Hermes data-flow work and ELF/JNI/Ghidra MCP investigation.

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
