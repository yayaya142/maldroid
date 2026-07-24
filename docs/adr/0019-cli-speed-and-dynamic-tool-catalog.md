# ADR 0019: CLI speed presets and a dynamically loaded tool catalog

Status: accepted — 2026-07-24

## Context

The owner reported that routine file work could take more than fifteen minutes and requested many
more static-research tools. Before this change, every generic model round carried 33 internal tool
schemas (about 4,700 tokens by a conservative character estimate); React Native carried 43 (about
5,900). Adding schemas directly would increase prompt evaluation, consume context, and make a small
local model choose among more similar operations on every round.

Investigations must still be able to run for hours. A speed control therefore cannot be implemented
as a hidden wall-clock deadline or phase ceiling that returns incomplete research as finished.

## Decision

- The terminal workspace has `fast`, `balanced`, and `deep` request presets. They set a per-response
  reasoning level, response-token cap, and maximum number of schemas sent to the model. They do not
  limit autonomous phases, total tool calls, or investigation duration.
- `balanced` is the default. A run can override it with `--speed`; `/speed` changes it without a
  server restart; `cli.speed_mode` persists the default. `/reasoning` remains an independent expert
  override for the current session.
- The case MCP server continues to publish every core plus active-profile tool. The dispatcher,
  path policy, validation, audit, and output limits are unchanged. Only the CLI model request uses
  a smaller selected schema view.
- Eight state/navigation tools remain loaded. A small default research set follows. Remaining
  capacity is filled by tools activated from the current objective. `MalDroid_search_tool_catalog`
  searches the authoritative active-profile registry; returned schemas are loaded on the next
  round and displace lower-priority defaults when necessary.
- Connected external MCP schemas participate in the same request selection and catalog activation.
  Their authority remains external and untrusted; selection does not extend MalDroid policy to
  them.
- The Web workspace is explicitly BETA and feature work is on hold. It keeps the existing full
  active-profile request behavior for now and does not expose CLI speed settings. Direct MCP clients
  also continue to discover the complete active-profile registry.
- Twelve bounded core tools add file fingerprint/entropy inspection, archive inventory and entry
  reads without extraction, structured-data queries, immutable SQLite inspection, large-source
  summaries, dependency maps, symbol tracing, file comparison, static decoding, decoded manifest
  analysis, and source-map inspection.

## Consequences

After the tool expansion, the complete generic registry contains 46 schemas (about 6,765 estimated
tokens). A representative generic CLI request carries 14 schemas/about 2,282 tokens in `fast`, 20
schemas/about 3,249 tokens in `balanced`, and 32 schemas/about 4,801 tokens in `deep`. The default
therefore sends roughly half the schema text of the expanded full registry while retaining access
to every tool through the catalog.

Speed presets reduce the cost of each model round but cannot guarantee wall-clock latency: model
size, hardware, prompt-cache state, evidence size, and external MCP latency still matter. A weak
model may need one catalog round before a specialized operation; the system prompt makes that step
explicit and unchanged catalog calls remain covered by the repeated-tool guard.

The CLI and BETA Web model-request surfaces temporarily differ. Their case format, MCP publication,
tool execution, and durable state remain shared. Web speed/catalog UX should be reconsidered only
after the owner lifts the hold and physical CLI acceptance is complete.
