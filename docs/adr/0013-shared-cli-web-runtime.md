# ADR 0013: Shared CLI and Web runtime

Status: accepted, 2026-07-15

## Context

MalDroid needs a modern browser workspace without allowing the terminal and browser products to
diverge. Starting two local models concurrently can also exhaust the owner's machine. A browser
surface introduces local cross-site request, DNS rebinding, unbounded file-read, and lifecycle
risks even when it binds only to loopback.

## Decision

`WorkspaceRuntime` is the single owner of llama.cpp, the case MCP server, the MCP client-side tool
executor, external MCP discovery, the append-only session, and `MalDroidAgent`. CLI and Web compose
this runtime instead of implementing separate model/tool loops.

A process-wide `RuntimeLease` permits one global MalDroid runtime. Web holds the lease for its
whole server lifetime and loads at most one case runtime. CLI holds it until llama.cpp and MCP have
fully stopped.

The Web server uses Starlette and Uvicorn, serves packaged dependency-free HTML/CSS/JavaScript, and
binds only to validated `127.0.0.1`. A random startup token is exchanged for an HTTP-only SameSite
cookie. API and WebSocket traffic requires it. Trusted Host validation and restrictive response
headers are mandatory.

Case files are listed and previewed only through the shared `ToolDispatcher` and `PathPolicy`.
Agent events are bridged to one WebSocket event queue; model work remains synchronous in a worker
thread and concurrent turns are rejected. UI activity reports tool and controller events but never
hidden chain-of-thought.

## Consequences

- CLI and Web use the same model, MCP, profile, state, report, path, and output-limit behavior.
- The Web shell can start without loading the GGUF; opening a case is the explicit memory boundary.
- Switching cases is slower than keeping multiple models loaded, but resource use is predictable.
- The frontend needs no Node toolchain, CDN, analytics, external fonts, or network dependency.
- Future user-facing operations must be added to the shared runtime/action layer and exposed on
  both surfaces, with parity tests.

