# ADR-0012: Semantic Research Memory and Bounded Working Context

Status: accepted
Date: 2026-07-15

## Context

Long investigations were promoting tool names, arguments, result dumps, and failures into free-form
Notes. Those Notes were then fed back into compaction, consuming context without preserving useful
research. Tool results and model reasoning also remained in the active conversation indefinitely,
and every autonomous work window repeated the original objective.

## Decision

Human/model research Notes are limited to insights, decisions, and hypotheses. Operational events
remain in append-only session and tool audit streams. Automatic continuity uses a typed Checkpoint
record containing objective, completed work, evidence learned, changed Finding/TODO IDs, unresolved
questions, uncertainty, status, and exact next action. Low-value automatic synthesis is skipped
instead of being persisted as research.

State schema v2 adds checkpoints and migrates v1 Notes without data loss. Complete paginated MCP
readback is available for Findings, Notes, TODOs, and Checkpoints. Deterministic reports are built
from this durable state.

The agent retains only a configurable number of full tool results and reasoning blocks in its
working context. Older payloads become small receipts while full JSONL/output remains on disk. The
next completion budget is reserved before the compaction threshold is calculated. The original
objective is stored once and restored only when actual compaction resets the conversation.

React Native and Native profiles automatically receive one bounded local methodology playbook.
This is preferable to an internal subagent in the current release: a subagent would add another
model lifecycle and state-merging boundary before durable memory has physical-host acceptance.

## Consequences

- Notes no longer double as tool logs or controller checkpoints.
- Long sessions retain recent evidence while shedding old payload weight without losing audit data.
- A fresh model can reconstruct research state through MCP and a human can rebuild a report at any
  point.
- Subagent orchestration remains deliberately deferred until typed state and long-run acceptance
  prove that a separate bounded context would add value.
