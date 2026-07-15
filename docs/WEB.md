# Web Workspace

MalDroid includes a local, loopback-only Web workspace backed by the same model, agent, MCP
transport, case state, tools, and reports as the terminal workspace.

## Start

```bash
maldroid server
maldroid server --port 8787
maldroid server --no-open
maldroid cli /path/to/case
```

Running `maldroid` with no arguments asks whether to start Web or CLI mode. Only one MalDroid Web
or CLI workspace may run at once. The Web process stays lightweight until an investigation is
opened; only then does it start llama.cpp and the case-scoped MCP server.

The server always binds to `127.0.0.1`. At startup it generates a random access token, opens the
tokenized URL in the default browser, and exchanges the token for an HTTP-only, SameSite cookie.
API and WebSocket calls without that cookie are rejected. Host validation, a restrictive Content
Security Policy, no-store responses, and frame blocking protect the local surface from unrelated
pages. There is no non-loopback option.

## Workspace model

- Each investigation in the left sidebar is a durable MalDroid case and conversation workspace.
- Opening an investigation starts a new append-only session while restoring the latest durable
  summary, Findings, TODOs, Notes, and Checkpoints.
- One case is active in model memory at a time. Switching cases stops the old runtime before
  loading the new one.
- The center pane contains multilingual chat and live agent progress. Individual Hebrew and Arabic
  messages are rendered RTL automatically; the application chrome remains English and LTR.
- The right inspector provides bounded case files and previews, structured research state, direct
  triage/report actions, and a live activity stream without exposing hidden model reasoning.

## Feature parity

The Web workspace exposes the same core controls as the terminal: dashboard/state, context,
profile mode, reasoning level, tools, files, Findings, TODOs, Checkpoints, session history,
timeline, inventory, indicator extraction, behavior triage, deterministic report generation,
knowledge search, compaction, clear-with-state-preservation, model/MCP status, and external MCP
connectors. The action menu provides non-chat operations; Files and Research provide persistent
state views.

Settings cover model paths and performance, context and research limits, cases, ports, and MCP
connectors. Persistent settings can only be changed while the model runtime is stopped. External
MCP URLs retain the same loopback and credential restrictions as the CLI.

The Model settings panel also controls automatic repeated-output recovery. It is enabled by
default. When triggered, Activity shows the stopped generation and new session; the same request
continues with durable and bounded recent context, without placing the repeated partial response in
the conversation or research records.

File listing and preview never read the filesystem directly. They call the shared dispatcher and
central `PathPolicy`, so case roots, evidence mappings, line limits, output limits, static-only
rules, and audit behavior remain identical across CLI and Web.

## Configuration

```toml
[web]
host = "127.0.0.1"
port = 8787
open_browser = true
```

`web.host` is fixed by schema and cannot be changed to a network interface.
