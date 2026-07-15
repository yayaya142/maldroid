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
- Once the model is ready, the labeled `Message MalDroid` composer is always visible at the bottom
  of the center pane. Enter sends and Shift+Enter inserts a newline; Actions are optional shortcuts.
- The right inspector provides bounded case files and previews, structured research state, direct
  triage/report actions, and a live activity stream without exposing hidden model reasoning.
- While the runtime starts or the model works, Chat shows a Live Work panel with elapsed time,
  research phase, tool-call count, approximate generated/context tokens, the current operation,
  and the latest three operational steps. It never renders private reasoning.
- During an active model turn, **Stop** closes the current generation stream and returns control to
  Chat without unloading llama-server. Partial generation is discarded; completed tools and durable
  research records remain available. If a synchronous tool is already running, the panel shows
  `Stopping` until that operation reaches its safe return boundary.
- The Files tab provides name/path filtering, collapsible directories, type-aware icons, item
  counts, selected-file state, keyboard navigation, and bounded previews with line numbers. A solid
  green marker identifies a file used in the latest turn and a green ring identifies a containing
  directory. Routine log paths are hidden by default; **Logs hidden** reveals them and remembers the
  browser preference.

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

Appearance can be switched between Dark and Light from either the header icon or Workspace
Settings. The preference is stored only in the local browser. Collapsing the project sidebar adds
a restore button to the workspace header; it remains available above the center pane at desktop
and mobile widths.

## Responsive layout

Use the browser at normal 100% zoom. On wide and standard laptop windows, Projects, centered Chat,
and the inspector share fluid columns. Their widths are clamped so the chat cannot be pushed beyond
the viewport. At 900 CSS pixels and below, Chat occupies the full screen while the ☰ and inspector
buttons open Projects and Files/Research/Activity as separate drawers with their own close controls.
Small-height and phone layouts reduce decorative welcome content while retaining the composer,
theme control, project access, and inspector access. No supported breakpoint requires horizontal
page scrolling.

The Model settings panel also controls automatic repeated-output recovery. It is enabled by
default. When triggered, Activity shows the stopped generation and new session; the same request
continues with durable and bounded recent context, without placing the repeated partial response in
the conversation or research records.

File listing and preview never read the filesystem directly. They call the shared dispatcher and
central `PathPolicy`, so case roots, evidence mappings, line limits, output limits, static-only
rules, and audit behavior remain identical across CLI and Web.

Latest-turn markers are derived only from bounded activity path arguments and reset on the next
turn or case switch. Hiding logs is a presentation filter only: it neither deletes log files nor
changes which files MalDroid tools can access.

## Configuration

```toml
[web]
host = "127.0.0.1"
port = 8787
open_browser = true
```

`web.host` is fixed by schema and cannot be changed to a network interface.
