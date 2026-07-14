# MalDroid

MalDroid is a local, static-analysis assistant for Android malware research. It manages
investigation cases, starts one local `llama-server`, exposes a small profile-specific tool set,
and persists evidence-backed findings. Investigation data is never sent to a cloud model.

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
maldroid resume
maldroid cases
```

Opening an existing directory creates only `.maldroid/` initially. Opening a file creates a
managed case and registers a symlink by default. No analysis starts merely because an artifact is
detected.

The chat supports `/help`, `/status`, `/profile`, `/tools`, `/files`, `/findings`, `/todo`, `/note`,
`/compact`, `/clear`, `/server`, `/knowledge`, and `/exit`.

## Configuration

Configuration is stored at `~/.config/maldroid/config.toml`:

```bash
maldroid config init
maldroid config show
maldroid config set llama.temperature 0.1
```

CLI options override configuration for one run. The preferred port is 7575; MalDroid selects a
free local port if the configured preference is occupied. An explicitly requested occupied port
is an error.

MalDroid rejects `--tools`, `--agent`, and MCP proxy flags in `extra_args`. Its tools are Python
handlers validated inside MalDroid, not `llama-server` built-in tools.

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
- Python venv unavailable on Kali: install `python3-full` and `python3-venv`.

Use `--debug` only when a traceback is needed. Uninstall safely with `./uninstall.sh`; cases and
user knowledge are retained by default.
