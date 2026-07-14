# Archived Handoff: MCP Fixed Port

Task: `MCP-002`

All MalDroid tools were exposed through loopback MCP Streamable HTTP and built-in chat tool calls
used the official MCP client. Port 8765 became fixed by default with collision failure instead of
fallback. The local suite contained 37 passing tests with 66% line coverage. Real model,
target-platform, and external desktop-client acceptance remained pending.
