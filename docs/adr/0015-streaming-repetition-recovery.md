# ADR 0015: Streaming repetition recovery

Status: accepted, 2026-07-15

## Context

Smaller local models can enter a mechanical generation loop and repeat a word, phrase, or final
character until the response budget is exhausted. Waiting for completion wastes time and context,
while retrying the same request in the same conversation can reproduce the failure. The aborted
text has no research value and must not become a Note, Finding, checkpoint, or model input.

## Decision

The local streaming client examines only a bounded 8,192-character suffix of answer and reasoning
channels. It stops strongly repeated word/phrase suffixes and extreme repeated-character suffixes,
closes the stream, emits metadata without the repeated content, and raises a dedicated controller
signal. This guard is controlled by `llama.repetition_recovery_enabled` and defaults to enabled.

The controller does not treat that signal as a transient request retry. It saves a bounded summary
of durable case state, creates a new append-only session, restores the active objective, adds the
most recent retained tool results as temporary untrusted working context, and continues with an
explicit non-repetition instruction. Tool payloads are not written into the persistent summary.
Recovery is limited to two fresh sessions per turn; a third loop stops safely with the durable
investigation state intact. Aborted generation text is never appended to chat history.

## Consequences

- Runaway output is interrupted before it consumes the full response/context budget.
- Recovery preserves Findings, TODOs, checkpoints, summary, and bounded recent working results.
- Session history shows detection and recovery metadata, but never stores the repeated partial text.
- Conservative thresholds may miss short loops; disabling the setting restores unguarded model
  streaming for diagnosis or models whose output legitimately repeats at those thresholds.
- Real-model tuning remains part of owner-host long-run acceptance.
