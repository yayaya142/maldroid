# ADR-0002: MCP Is the Tool Transport Boundary

Status: accepted  
Date: 2026-07-14

## Context

MalDroid tools must be convenient for external MCP clients while retaining the existing case,
profile, path, output, and audit controls. Enabling llama.cpp built-in tools or its experimental MCP
proxy would grant authority outside the Python policy boundary.

## Decision

MalDroid exposes its existing registry through the official Python MCP SDK using stateless
Streamable HTTP at `/mcp`. It binds only `127.0.0.1`, enables DNS-rebinding protection, and reports
the effective port and endpoint. Normal model tool calls use the official MCP client to reach this
server. The MCP call handler delegates to the existing serialized `ToolDispatcher`; it does not
implement a second execution path.

The fixed default port is 8765. A collision always fails; MalDroid never changes the MCP endpoint
silently. Users may persist a different fixed port in configuration or provide a one-run CLI
override. The server publishes only core plus active-profile tools. llama.cpp built-in tools, agent
mode, and MCP proxy remain forbidden.

## Consequences

- External MCP clients and the built-in chat share exactly the same schemas and policy checks.
- A saved client endpoint remains stable across runs unless the user changes configuration.
- Local clients can invoke case tools for the lifetime of the server; researchers must not expose
  the loopback endpoint through tunnels or reverse proxies.
- The official `mcp` SDK becomes a runtime dependency and its supported major version is pinned.
