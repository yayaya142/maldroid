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
and stderr. Exit, Ctrl+C, `SIGHUP`, and SIGTERM terminate the process group gracefully, then force
it only after a timeout. An interpreter-exit hook provides a final normal-exit safeguard. Command
construction remains centralized.

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

All public MalDroid-managed MCP tool names use the `MalDroid_` prefix. The registry applies this
centrally before schemas are exposed, so profile discovery, model calls, external clients, audit
records, and direct internal dispatch all use the same unambiguous names.

## Message and tool lifecycle

The request contains a short system prompt, one small active-profile instruction, persistent case
summary, active conversation, and only core plus active-profile schemas. Parallel calls are off.
Each returned call is sent through the official MCP client, validated by both MCP input schemas and
the dispatcher, executed serially, serialized as a `tool` role message, persisted, and sent back.
Eight investigation tool rounds form one autonomous phase rather than a terminal limit. At a phase
boundary the controller saves an MCP checkpoint, compacts context, restores the original objective,
and continues without user input. A context-threshold crossing triggers the same rollover inside
the active phase. Phases are unlimited; the legacy ceiling key is accepted only for configuration
compatibility and is not enforced. Transient model calls use bounded retries. After meaningful investigation activity, a final response is
not accepted until the model saves a note/finding checkpoint. If it ignores the reminder, the agent
saves its draft response automatically through the audited MCP note tool. Prose that resembles a
tool call is never executed.

## Profile selection

Profile selection is controller-owned and automatic unless the operator explicitly locks a manual
profile. A bounded detector scores filesystem names, registered evidence roots, archive central
directory entries, ELF magic, and small candidate content samples. It returns the selected profile,
confidence, all scores, concrete indicators, scan totals, and truncation state. Framework evidence
outranks capped incidental Native evidence.

Detection runs before a turn and after evidence registration. An actionable change is persisted,
recorded as a session event, announced to the terminal, and followed by rebuilding the tool schema
set for the next model request. The core MCP detector is also model-callable. For ambiguous evidence,
the model can submit a schema-validated selection and reason; this capability is removed from model
schemas while a manual profile lock is active.

The terminal layer subscribes to bounded agent lifecycle events rather than parsing model prose.
It renders model waits, tool start/result, checkpoint, and compaction activity while the agent and
MCP dispatcher remain the source of execution truth. Prompt history and completion are local-only;
the terminal UI has no additional network or filesystem authority.

The local model client streams content, reasoning, tool-call fragments, and final usage. Tool calls
are reconstructed only from structured API deltas. The terminal uses streaming events for live
token/context telemetry; the complete reconstructed assistant message remains the sole history and
tool-loop input.

Reasoning effort is a per-request model-client property. The configured human-readable level maps
to llama.cpp `thinking_budget_tokens`, can change between tool rounds without a server restart, and
is recorded as a session event. No command-line reasoning budget is set, preserving dynamic control.

## Context and retrieval

Conversation size is conservatively estimated. At 72% usage by default, the UI automatically saves
a structured summary and starts a compact context before or after the next turn. If model-based
summarization fails, findings, recent notes, open TODOs, profile, and the prior summary form a
deterministic fallback. Compaction never deletes full session history, findings, notes, or TODOs.
Large evidence enters context only through search results, bounded ranges, indexed chunks, or
modules. Knowledge uses matching excerpts rather than prompt injection.
