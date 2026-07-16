# Architecture

## Shared product surfaces

`WorkspaceRuntime` owns the complete case execution stack: llama.cpp process, local MCP server,
official MCP client, dispatcher context, external MCP runtime, session, and agent. `InteractiveChat`
and the loopback Web application are presentation adapters over that runtime. See ADR 0013.

The Web server is a lightweight control plane until a case is activated. Its three-pane frontend
uses authenticated same-origin HTTP/WebSocket endpoints for projects, bounded file inspection,
research state, actions, settings, and activity. It never receives a direct unrestricted file API.
A global file lease prevents concurrent CLI/Web model runtimes.

The browser owns presentation-only preferences such as dark/light appearance and collapsed panes;
these do not enter case or model configuration. The Files inspector renders the bounded dispatcher
inventory as a searchable, collapsible tree, while all reads still pass through `PathPolicy`.
It derives latest-turn file markers from bounded tool activity path arguments and clears them at
the next turn or case switch. Log-path suppression and its persisted reveal toggle are strictly
browser presentation: the dispatcher inventory, audit data, and model/tool authority are unchanged.
Composer visibility follows explicit runtime state; CSS cannot infer or override model readiness.

The desktop grid uses one shared compact clamped width for both project and inspector panes plus a
zero-minimum flexible chat column. Equal side columns keep Chat mathematically centered on the
viewport at 100% zoom. If only one pane is collapsed, a bounded inner-content offset keeps welcome,
messages, Live Work, and the composer centered on the viewport while the remaining pane stays
usable. At
900 CSS pixels and below the chat becomes the sole layout column; Projects and the full
Files/Research/Activity inspector become independent keyboard-accessible drawers. Height
breakpoints compact nonessential welcome content without shrinking the chat composer or model
controls.

During startup and active turns, the center pane consumes the same bounded WebSocket activity
events as the Activity inspector to render Live Work telemetry. It distinguishes prompt loading,
cached prompt tokens, first-token latency, generation, tools, recovery, and compaction. Elapsed time
is browser-local; phase, tool count, and token estimates are presentation metrics rather than durable case state.
The surface describes operations and outcomes only. Hidden reasoning and raw evidence payloads
remain outside the DOM.

Web model turns run as asynchronous WebSocket tasks so the same authenticated connection can accept
a Stop request while the synchronous controller is working. Cancellation closes the current model
stream and is checked at every model/tool boundary. Partial generation is discarded; durable state
and completed tool results remain available, and llama-server stays loaded. An already-running
synchronous tool finishes before cancellation is acknowledged as complete. See ADR 0016.
Client-side socket transitions are consumed serially, preventing a fast turn from overtaking an
earlier authoritative bootstrap/history reload.

## Update lifecycle

The explicit `maldroid update` maintenance path is separate from investigation execution. It clones
the fixed official repository into `TemporaryDirectory`, invokes `install.sh --upgrade`, and then
deletes the source tree. Upgrade mode replaces only the private application venv. It keeps the old
venv as `venv.previous` until installation and doctor verification finish, restoring it through an
EXIT trap on failure. The global runtime lease prevents concurrent model or Web work. See ADR 0014.

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
- `agent`, `session_manager`, and `ui`: long-running tool controller, semantic checkpoints,
  bounded working context, append-only sessions, compaction, and interactive research workspace.
- `tools.registry` and `tools.dispatcher`: schema discovery, profile filtering, execution, and
  truncation.
- `large_files`: contentless FTS5 token index plus source offsets.
- `knowledge_manager`: Markdown discovery, metadata, FTS5 retrieval, and bounded reads.
- `investigation`: stable findings, evidence references, notes, and TODOs.
- `updater`: fixed-remote temporary clone, transactional installer invocation, and cleanup.

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
Eight investigation tool rounds form one autonomous work window rather than a terminal or context
limit. At a window boundary the controller saves a meaningful MCP checkpoint and continues without
discarding conversation context. Compaction occurs only when the configured context-usage threshold
is actually crossed. Phases are unlimited; the legacy ceiling key is accepted only for configuration
compatibility and is not enforced. Transient model calls use bounded controller retries; SDK
retries are disabled so attempts cannot multiply invisibly. Non-transient request errors fail
immediately.

Completed tool outcomes are fingerprinted from their canonical call and result. Three consecutive
unchanged outcomes tell the model to change strategy; five end the turn with a durable, user-visible
fallback instead of consuming unlimited context. This operational guard writes session/activity
events only and never promotes the loop itself into a Note, Finding, or synthetic checkpoint.

After the first substantive evidence operation, an empty state triggers an internal reminder to
create and maintain TODOs and Findings. A final response is not accepted until a typed semantic
checkpoint follows the latest investigation activity. Checkpoints contain research progress,
evidence learned, changed durable IDs, uncertainty, unresolved questions, and an exact next action;
they never contain tool arguments, result dumps, or failures. If the model has not saved one, the
controller derives it from the accepted semantic draft without another generation. Low-value
fallback content is skipped and operational detail remains in session/audit streams. Prose that
resembles a tool call is never executed.

## Profile selection

Profile selection is controller-owned and automatic unless the operator explicitly locks a manual
profile. A bounded detector scores filesystem names, registered evidence roots, archive central
directory entries, ELF magic, and small candidate content samples. It returns the selected profile,
confidence, all scores, concrete indicators, scan totals, and truncation state. Framework evidence
outranks capped incidental Native evidence.

Detection runs once for the active evidence set and refreshes after evidence registration,
explicit detection, or re-enabling automatic mode. An actionable change is persisted,
recorded as a session event, announced to the terminal, and followed by rebuilding the tool schema
set for the next model request. The core MCP detector is also model-callable. For ambiguous evidence,
the model can submit a schema-validated selection and reason; this capability is removed from model
schemas while a manual profile lock is active.

The terminal layer subscribes to bounded agent lifecycle events rather than parsing model prose.
It renders model waits, tool start/result, checkpoint, and compaction activity while the agent and
MCP dispatcher remain the source of execution truth. Prompt history and completion are local-only;
the terminal UI has no additional network or filesystem authority.

The local model client streams prompt progress, content, reasoning, tool-call fragments, finish
reason, final usage, and llama.cpp timings. Requests enable prompt caching and SSE keepalive; token
events are throttled before reaching Web/CLI presentation queues. Tool calls are reconstructed only
from structured API deltas. Completed-turn reasoning is stripped before the next user turn while
remaining available inside the current tool loop and append-only session record. A reasoning-only
empty finish receives one history-safe recovery with reasoning disabled. The complete reconstructed
assistant message remains the sole history and tool-loop input. See ADR 0017.

An enabled-by-default repetition guard examines a bounded suffix of answer and reasoning streams.
When a word, phrase, or character enters a strong mechanical loop, the client closes the stream
before the partial message reaches history. The controller writes metadata only, summarizes durable
state and bounded recent tool results, creates a new append-only session, restores the objective,
and continues. Two recoveries are permitted per turn; further repetition stops safely. ADR 0015
defines the thresholds, persistence boundary, and opt-out.

Runtime shutdown is deterministic and generation-free. It preserves any prior model synthesis and
replaces one marked durable-state section built from typed case records. Repeated shutdowns therefore
do not recursively grow the summary, and MCP/model process cleanup continues even if summary or one
listener cleanup step fails. See ADR 0018.

## External MCP connectors

The persistent external connector registry is separate from the case-scoped MalDroid MCP server.
It stores validated loopback URLs and nicknames under the configuration directory and keeps an
append-only connector history. Streamable HTTP and legacy SSE use the official MCP clients.

At chat startup, each configured server is discovered independently. Its schemas are added to the
model under a collision-resistant `MCP_<nickname>_` namespace; unavailable servers are omitted
without failing the case. Calls route directly to the owning MCP server, returned output is capped
and overflowed into the case, and invocation status joins the case tool audit and session JSONL.
The external process remains responsible for argument semantics, filesystem authority, and side
effects, so its descriptions and results are treated as untrusted and never represented as
MalDroid-case-policy enforcement.

Reasoning effort is a per-request model-client property. The configured human-readable level maps
to llama.cpp `thinking_budget_tokens`, can change between tool rounds without a server restart, and
is recorded as a session event. No command-line reasoning budget is set, preserving dynamic control.

## Context and retrieval

Conversation size is conservatively estimated. At 72% usage by default, the UI automatically saves
a structured summary and starts a compact context during an active rollover or before the next turn;
the Web never hides an already-finished answer behind post-turn compaction. If model-based
summarization fails, findings, recent notes, open TODOs, profile, and the prior summary form a
deterministic fallback. Compaction never deletes full session history, findings, notes, or TODOs.
Large evidence enters context only through search results, bounded ranges, indexed chunks, or
modules. Knowledge uses matching excerpts rather than prompt injection.

Broad repository traversal never follows nested symbolic links and skips routine internal/generated
directories. Explicit registered evidence roots and explicitly requested generated outputs remain
available through `PathPolicy`. Exact search, multi-family behavior triage, indicator extraction,
framework search, line-range preview, and large-bundle metrics stream bounded chunks. Search
previews center on the match even inside a minified logical line. When a global result, file, or time
budget stops a scan, the result distinguishes exact totals from lower bounds and records the
truncation reason; saved match artifacts are bounded as well as the inline MCP response.

The controller reserves the next completion budget when calculating context pressure. Only the six
most recent tool results and reasoning blocks are retained in full by default; older payloads become
small receipts whose complete contents remain in session JSONL or saved output. The active objective
is not repeated at every tool window. React Native and Native profiles receive one bounded local
methodology brief when activated.
