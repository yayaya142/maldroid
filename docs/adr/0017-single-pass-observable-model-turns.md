# ADR 0017: Keep local model turns observable and single-pass

Status: accepted — 2026-07-16

## Context

The Web surface could remain in a working state after the model had already produced its answer,
because it synchronously compacted context before returning the message. Investigation finals could
also trigger a second full generation solely to ask the model for a checkpoint. On weaker local
models, repeated profile scans, retained cross-turn reasoning, SDK retries nested inside controller
retries, and reasoning-only length finishes compounded first-token and final-answer latency.

Current llama.cpp exposes streamed prompt progress, prompt caching, SSE keepalive, finish reasons,
usage, and timing metadata. Gemma 4 guidance requires generated thoughts to be removed between
completed conversation turns while allowing them inside one tool-calling turn.

## Decision

- The MalDroid controller is the only retry authority. The OpenAI-compatible SDK performs zero
  retries, and the controller retries only connection, timeout, rate-limit, conflict, and server
  failures. A configurable stream-idle timeout bounds stalled requests.
- Requests enable llama.cpp prompt caching, prompt-progress events, and SSE keepalive. The client
  records finish reason, prompt/cache/completion usage, first-token latency, and server timings,
  while throttling high-frequency generation events.
- Completed-turn `reasoning_content` is removed before the next user message. Reasoning remains
  available during the current tool loop and in the append-only session record.
- Automatic profile detection is cached for the active evidence set. Registration of new evidence,
  explicit detection, or returning to automatic profile mode invalidates or refreshes it.
- A visible final answer is never delayed by a post-turn Web compaction. Context is compacted at
  the next preflight boundary or during an active context rollover.
- When investigation work needs a final checkpoint, the controller saves a bounded semantic
  checkpoint directly from the accepted draft instead of asking for another model generation.
- A reasoning-only or otherwise empty generation is excluded from conversation history and gets
  one immediate recovery attempt with reasoning disabled. A second empty result fails with the two
  finish reasons and a concrete template/token diagnostic.

## Consequences

Normal investigation finals require fewer generations and repeated chat turns avoid redundant
filesystem scans and old thought tokens. Web users can distinguish prompt evaluation, first-token
wait, generation, tools, recovery, and compaction without exposing private reasoning.

The reduced reasoning budgets prioritize local responsiveness; users can still select `high` or
`unlimited`. Real GGUF throughput, cache-hit ratios, tool-call quality, and empty-response recovery
remain part of the physical macOS acceptance gate. No execution, network, profile-tool exposure, or
case-path boundary changes.

## References

- [llama.cpp server options and response fields](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp function-calling templates](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
- [Gemma 4 prompt formatting](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4)
- [Gemma 4 function calling](https://ai.google.dev/gemma/docs/capabilities/text/function-calling-gemma4)
- [openai-python retries and timeouts](https://github.com/openai/openai-python)
