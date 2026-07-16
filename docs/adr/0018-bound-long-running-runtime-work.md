# ADR 0018: Bound long-running runtime work without sacrificing durable research

Status: accepted — 2026-07-16

## Context

MalDroid investigations are expected to run for hours against repositories and generated artifacts
that may contain hundreds of thousands of lines. Several paths were bounded only at the model-facing
response: broad searches could still traverse nested symbolic links or write very large intermediate
artifacts, shutdown could start another model generation, and a weak model could repeat an unchanged
tool call indefinitely. Those behaviors waste context, disk, and wall-clock time even when the UI
eventually shows a small result.

The CLI and Web surfaces also need the same recovery semantics. A stopped or reconnected Web client
must display the authoritative runtime/session state rather than a stale optimistic selection.

## Decision

- Runtime shutdown never asks the model to compact or summarize. It deterministically persists the
  current profile, Findings, TODOs, Notes, Checkpoints, and any prior model synthesis. Repeated
  shutdowns replace one marked durable-state section instead of recursively embedding summaries.
- The agent fingerprints each completed tool outcome from the tool name, canonical arguments, and
  result hash. Three consecutive identical outcomes inject a strategy-change instruction and visible
  event; five stop the turn with a persisted safe response. Existing durable records remain intact,
  and no synthetic research note or checkpoint is created merely because a loop was stopped.
- Broad filesystem scans use one non-following walker. Nested symbolic links and routine generated or
  internal directories are excluded, while an explicitly requested registered evidence root or
  generated output remains readable through `PathPolicy`.
- Core exact search, behavior-family triage, indicator extraction, framework search, and large-bundle
  inspection stream their inputs and enforce global result, time, and artifact budgets. Bounded
  range reads never materialize one oversized logical line, and exact-search previews stay centered
  on the matching region. Partial scans report `scan_complete`, a truncation reason, and whether
  totals are exact.
- Conversation, activity, connector, and session views stream append-only JSONL into bounded deques.
  Web project activation, commands, and runtime stop are mutually exclusive with a model turn; a
  reconnect reloads authoritative workspace/history state and consumes socket transitions in order.

## Consequences

Normal answers and shutdown are no longer delayed by hidden follow-up generations. Weak models can
recover from one repeated strategy without consuming an unbounded number of rounds, and very large
repositories cannot expand through unregistered nested links or unbounded match artifacts.

Stopping five identical static tool outcomes may terminate a model that intended to poll an
unchanging result. MalDroid's managed investigation tools are static and do not require polling, so
the operator can retry with a more specific request if that conservative guard fires incorrectly.
Counts from an early-stopped scan are explicitly lower bounds rather than misleading exact totals.

Physical Gemma 4 throughput, long-run checkpoint quality, Ghidra MCP behavior, and macOS UI
acceptance remain part of `PLATFORM-011`; this decision is covered locally with deterministic
fixtures and does not claim real-model acceptance.
