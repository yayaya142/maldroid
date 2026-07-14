# ADR-0010: Decouple Work Checkpoints from Context Compaction

Status: accepted  
Date: 2026-07-14

## Context

Long investigations need periodic durable state without stopping the agent. The original autonomous
controller used the same rollover path for a configured tool-round window and actual context
pressure. Consequently, every window caused model summarization and context replacement even when
tens of thousands of tokens remained. Automatic notes also emphasized tool names rather than the
evidence learned or work remaining.

## Decision

A tool-round boundary saves a bounded, meaningful checkpoint and starts the next autonomous work
window without compacting. Only `limits.auto_compact_ratio` may trigger automatic context
compaction. The checkpoint records the objective, bounded tool arguments and result previews,
current Findings and TODOs, and an explicit continuation action.

The controller also requests TODO/Finding maintenance after substantive evidence work begins and
requires a fresh synthesis note after the latest investigation operation before accepting a final
answer. The model remains responsible for interpreting evidence; the fallback note records observed
tool results but does not manufacture findings.

## Consequences

- Long investigations retain usable context across arbitrary tool-window boundaries.
- Durable checkpoints remain frequent without creating a compaction loop.
- TODO and Finding files become visible working state rather than optional end-of-task artifacts.
- Automatic fallback preserves evidence context while avoiding unsupported synthesized findings.
- Context compaction can still happen mid-window when the measured threshold is genuinely crossed.
