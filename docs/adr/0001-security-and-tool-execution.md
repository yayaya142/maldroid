# ADR-0001: Tool execution remains inside MalDroid

Status: accepted

MalDroid sends OpenAI-compatible schemas to a local model, but executes handlers inside its Python
process. Those MCP handlers retain profile, path, timeout, output, and audit policy even after
prompt injection. Separately, the owner explicitly enables llama.cpp WebUI built-in host tools and
accepts that they can execute commands and mutate files outside MalDroid's case boundary. Agent mode
remains disabled, and both services remain loopback-only.
