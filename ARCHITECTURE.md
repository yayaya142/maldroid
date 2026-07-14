# Architecture

## Process and trust boundary

```text
Researcher terminal
  -> MalDroid CLI
       -> official MCP client -> loopback Python MCP server -> ToolDispatcher -> Python tools
       -> validated loopback OpenAI-compatible requests -> one child llama-server process
```

Evidence, knowledge, and model output are untrusted. `llama-server` receives schemas and returns
requests; it never receives authority to execute tools. `mcp_server` publishes only active-profile
schemas over loopback Streamable HTTP. `ToolDispatcher` independently enforces
profile enablement, Pydantic schemas, path boundaries, output limits, structured errors, and audit
logging. External static utilities are temporary allowlisted subprocesses with `shell=False`.

## Components

- `config`: validated TOML, safe defaults, and dangerous-flag rejection.
- `case_manager`: case lifecycle, recent registry, atomic metadata and state.
- `evidence_manager`: non-overwriting symlink/copy registration and source provenance.
- `process_manager` and `llama_adapter`: command construction, ports, health, logs, signals, and
  child shutdown.
- `llama_client`: normalized Chat Completions messages, tool calls, and `reasoning_content`.
- `mcp_server`: MCP protocol discovery/calls, loopback port lifecycle, and the internal MCP client.
- `agent`, `session_manager`, and `ui`: bounded tool loop, append-only sessions, compaction, and
  line-oriented chat.
- `tools.registry` and `tools.dispatcher`: schema discovery, profile filtering, execution, and
  truncation.
- `large_files`: contentless FTS5 token index plus source offsets.
- `knowledge_manager`: Markdown discovery, metadata, FTS5 retrieval, and bounded reads.
- `investigation`: stable findings, evidence references, notes, and TODOs.

Dependencies point inward toward domain models and policies. Tool modules depend on managers;
managers do not depend on tool modules.

## Case lifecycle

A managed case receives the full user-facing layout. An existing directory initially receives only
`.maldroid`. `case.toml` contains identity metadata and `state.json` contains versioned mutable
state. Writes use a lock, temporary file, fsync, and atomic replace. Session and audit streams are
append-only JSONL.

## Server lifecycle

MalDroid validates the binary and model, chooses port 7575 or a safe fallback, and starts the child
in a new process group. Model API authentication is disabled by default for direct loopback use; if
enabled, a per-run key is generated and redacted. MalDroid polls `/v1/health` and captures stdout
and stderr. Exit, Ctrl+C, and SIGTERM terminate the process group gracefully, then force it only
after a timeout. Command construction remains centralized.

The owner-controlled llama.cpp WebUI enables its MCP CORS proxy and all built-in host tools. These
tools execute in the llama-server process with host permissions and are explicitly outside
MalDroid's case path, output, and audit policy. MalDroid-managed chat continues to receive only the
active profile schemas and execute them through the separate Python MCP dispatcher.

The Python MCP server binds `127.0.0.1` only, enables MCP transport DNS-rebinding protection, and
uses a pre-bound socket. Its fixed default port is 8765. Every collision fails rather than changing
the client endpoint silently. Interactive chat owns the MCP lifecycle, while `maldroid mcp serve`
provides a model-independent foreground lifecycle. Both print the effective endpoint. The MCP
transport accepts browser origins only from the managed loopback llama-server port and emits the
CORS headers required by the llama.cpp WebUI. Other browser origins remain rejected.

## Message and tool lifecycle

The request contains a short system prompt, one small active-profile instruction, persistent case
summary, active conversation, and only core plus active-profile schemas. Parallel calls are off.
Each returned call is sent through the official MCP client, validated by both MCP input schemas and
the dispatcher, executed serially, serialized as a `tool` role message, persisted, and sent back.
Eight tool rounds is the hard default. Prose that resembles a tool call is never executed.

## Context and retrieval

Conversation size is conservatively estimated. The UI warns at 75% and blocks ordinary requests at
85% pending compaction. Compaction saves full history and creates a structured summary without
deleting findings or TODOs. Large evidence enters context only through search results, bounded
ranges, indexed chunks, or modules. Knowledge uses matching excerpts rather than prompt injection.
