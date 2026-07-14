# ADR-0001: Tool execution remains inside MalDroid

Status: accepted

MalDroid sends OpenAI-compatible schemas to a local model, but executes handlers inside its Python
process. llama.cpp built-in tools, agent mode, and MCP proxy are disabled because they include host
filesystem mutation and command execution outside MalDroid's case boundary. This keeps profile,
path, timeout, and output policy deterministic even after prompt injection.

