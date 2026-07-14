# ADR-0011: Persistent External MCP Connectors

Status: accepted  
Date: 2026-07-14

## Context

The operator needs the MalDroid CLI agent to use other MCP servers without repeatedly editing
llama.cpp WebUI settings. Connector URLs must remain available across sessions and installation
changes, while tool collisions and accidental evidence exposure must be controlled.

## Decision

MalDroid stores external MCP connectors and append-only lifecycle history in its configuration
directory. Registration requires only a loopback HTTP(S) URL and an optional nickname. `/sse`
selects legacy SSE; other paths use Streamable HTTP. URLs containing remote hosts, embedded
credentials, query parameters, or fragments are rejected.

Startup discovers each server independently through the official MCP client. Tools receive a
bounded, collision-resistant `MCP_<nickname>_` alias before entering model schemas. Calls route to
the original MCP tool, results are size-limited with case-local overflow, and status is written to
case/session audit. Offline connectors are omitted with a warning instead of blocking MalDroid.

## Consequences

- Adding a connector is a single command and does not require WebUI configuration changes.
- Connector state and history survive reinstall and default uninstall behavior.
- Explicit `mcp remove` deletes one connector; approved uninstall configuration removal deletes all.
- External servers retain their own filesystem and process authority. MalDroid cannot enforce case
  path policy on their implementation, so metadata/results are untrusted and the boundary is shown
  in documentation and tool descriptions.
- Remote MCP services and URL-embedded authentication are intentionally unsupported to prevent
  accidental evidence disclosure and secret persistence.
