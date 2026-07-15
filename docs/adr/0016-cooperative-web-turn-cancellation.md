# ADR 0016: Cooperative Web turn cancellation

Status: accepted, 2026-07-15

## Context

Long local-model turns need an explicit researcher-controlled Stop action. The original WebSocket
handler awaited the complete synchronous agent turn, so it could not receive another message while
the model was generating. Hiding progress in the browser would not stop model or tool work, while
terminating the shared llama-server would make the workspace expensive and fragile to resume.

## Decision

Each Web chat turn runs in a dedicated asynchronous task backed by the existing worker thread. The
WebSocket remains available for a `stop` message. Cancellation sets a thread-safe controller flag,
closes the active llama.cpp response stream when possible, and is checked before and after model
requests and every tool boundary. Partial generated text is discarded rather than appended to
history.

Completed tool results and durable Findings, TODOs, Notes, and Checkpoints remain intact. The agent
records a `turn_cancelled` session event and adds a small system boundary that prevents the next
message from silently continuing the stopped objective. The shared model runtime remains loaded.

Already-running synchronous tools are not force-killed because their cancellation semantics differ
and an unsafe interruption could leave incomplete output. Stop waits for that bounded operation to
return, records its completed result, and exits at the next safe boundary. Process-aware tool
cancellation remains part of the broader `AGENT-018` work.

## Consequences

- The researcher can stop generation without restarting the model or losing durable work.
- The Web UI can acknowledge Stop immediately and report that it is finishing a safe boundary.
- Cancellation is cooperative for synchronous Python/external MCP calls, so a slow active tool may
  delay final acknowledgement until it returns.
- Closing or disconnecting the active Web workspace also requests cancellation so invisible model
  work does not continue indefinitely.
