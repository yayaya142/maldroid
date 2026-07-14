# ADR-0009: Owner-Controlled llama.cpp Host Tools Are Enabled

Status: accepted  
Date: 2026-07-14

## Context

The project owner uses the llama.cpp WebUI directly and wants to select from its complete built-in
tool set. Current llama.cpp exposes `read_file`, `file_glob_search`, `grep_search`,
`exec_shell_command`, `write_file`, `edit_file`, `apply_diff`, and `get_datetime` through
`--tools all`. These tools are not restricted to a MalDroid case.

## Decision

MalDroid enables `--ui`, `--ui-mcp-proxy`, and `--tools all` by default. The model server remains
bound to loopback. The WebUI lets the owner choose which built-in tool to use. Configuration exposes
separate booleans for the UI, proxy, and built-in tools, while direct duplicates in `extra_args`
remain rejected.

MalDroid-managed chat does not receive these built-in schemas. It continues to call only the core
plus active-profile schemas through the Python MCP dispatcher.

## Consequences

- WebUI tools can execute shell commands and read, write, or edit any file accessible to the
  llama-server process.
- Built-in activity is outside MalDroid's path policy, output limits, and execution audit.
- Evidence remains untrusted; built-in tools should be used only under direct researcher control.
- `doctor` reports this host-authority surface as a warning instead of implying case isolation.
