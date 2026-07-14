# Static Tool Compatibility

| Tool | Role | Policy |
|---|---|---|
| llama-server | Local model API, WebUI, host tools, and tool-call formatting | User-supplied; `--jinja`, loopback WebUI/MCP proxy, `--tools all`; agent mode disabled |
| ripgrep | Exact and regex text search | Preferred; argument array and timeout |
| strings | Static printable-string extraction | Optional; output saved and bounded |
| readelf/objdump/nm | Future Native profile | Allowlisted arguments only; never execute evidence |
| JADX | Researcher-provided decompiler output | MalDroid V1 consumes output; it does not automatically decompile APKs |
| Blutter | Future Flutter adapter | Optional, version-sensitive, explicit user invocation only |

Record exact versions inside case state when an adapter runs. Never claim compatibility merely
because an executable is present.
