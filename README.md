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
git clone <repository>
cd maldroid
./install.sh
```

The installer creates `~/.local/share/maldroid/venv`, installs MalDroid there, and creates
`~/.local/bin/maldroid`. It never installs Python packages into the system interpreter. Preview
all actions with `./install.sh --dry-run`.

The first-use setup requests the local `llama-server` and GGUF paths. The supplied macOS default
model is:

```text
/Users/shaio/Desktop/Tools/Ai Models/gemma-4-12B-it-qat-q4_0.gguf
```

Validate model tool calling before research use:

```bash
maldroid doctor --show-command
maldroid doctor --model-tool-test
```

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

The chat supports `/help`, `/status`, `/profile`, `/tools`, `/files`, `/findings`, `/todo`, `/note`,
`/compact`, `/clear`, `/server`, `/knowledge`, and `/exit`.

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

The configured MCP port is only preferred. If it is occupied, MalDroid binds a free local port and
prints it. An explicitly supplied occupied `--port` on `mcp serve`, or `--mcp-port` on normal chat,
fails. Tool discovery always returns only core
tools plus the case's active profile. The endpoint is intentionally not exposed beyond loopback;
any local client connected to it can invoke case-scoped tools until the server stops.

## Configuration

Configuration is stored at `~/.config/maldroid/config.toml`:

```bash
maldroid config init
maldroid config show
maldroid config set llama.temperature 0.1
```

CLI options override configuration for one run. The preferred model port is 7575 and the preferred
MCP port is 8765. MalDroid selects a free local port if a configured preference is occupied. An
explicitly requested occupied port is an error.

MalDroid rejects `--tools`, `--agent`, and MCP proxy flags in `extra_args`. Its MCP server is the
Python security boundary; `llama-server` built-in tools and experimental MCP proxy remain disabled.

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
- MCP connection failure: copy the endpoint printed by the current process; a fallback port may
  differ from 8765.
- Python venv unavailable on Kali: install `python3-full` and `python3-venv`.

Use `--debug` only when a traceback is needed. Uninstall safely with `./uninstall.sh`; cases and
user knowledge are retained by default.
