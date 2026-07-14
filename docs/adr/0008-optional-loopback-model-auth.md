# ADR-0008: Loopback Model API Authentication Is Optional

Status: accepted  
Date: 2026-07-14

## Context

MalDroid owns a local `llama-server`, but researchers may also use that server directly through a
local UI or OpenAI-compatible client. A random key on every start prevents those clients from
reconnecting without manually discovering a new secret. The server host is already restricted to
loopback by validated configuration.

## Decision

`llama.api_key_enabled` controls model API authentication and defaults to `false`. When disabled,
MalDroid omits `--api-key` and its internal client uses the unauthenticated loopback API. When
enabled, MalDroid generates a random key for that process, passes it only to the managed client, and
redacts it from displayed commands. Non-loopback model hosts remain forbidden.

This setting changes only the llama.cpp model API on port 7575. The case-scoped MCP server remains a
separate loopback service on port 8765 with its existing path, tool, profile, and output policies.

## Consequences

- Local llama.cpp UIs and API clients work without a key by default.
- Any process running as the same machine user can call the unauthenticated model API while it is
  active; users who require local authentication can enable it explicitly.
- Enabling authentication intentionally favors managed MalDroid chat over stable external-client
  credentials because the key remains random per run.
