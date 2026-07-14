# Ordered Next Steps

1. `REL-001` — On the user's macOS host, run installer dry-run, installation, doctor command
   preview, and `doctor --model-tool-test` using the authorized Gemma 4 GGUF. Record llama.cpp
   version and `/props` template behavior. Acceptance: structured array/object tool call and final
   response pass without built-in tools. Connect an external MCP client to the printed endpoint,
   confirm the saved fixed `http://127.0.0.1:8765/mcp` endpoint reconnects across runs, list tools,
   and call `read_case_state`. Install the generated wheel, enable zsh completion, and smoke-test
   `--help`, `config validate`, `doctor --json`, and `mcp client-config`.
   Verify the public clone from `https://github.com/yayaya142/maldroid.git` in a clean directory.
   Confirm installation succeeds despite unrelated global `pip` index configuration; use
   `MALDROID_PIP_INDEX_URL` only when an approved private mirror is intentionally required.
   Verify `SYSTEM_PROMPT.md` in one direct external-client session and confirm the model starts with
   `read_case_state` and `list_case_files` before bounded evidence reads.
   Confirm the llama.cpp UI connects without an API key under the default configuration, then
   enable `llama.api_key_enabled` once and verify the authenticated managed-client path.
2. `REL-002` — Run the full suite and installer lifecycle on Kali rolling and Apple Silicon.
3. `COMPAT-001` — Expand benign multi-architecture ELF and versioned Blutter fixtures on target
   platforms and record exact external-tool versions.
4. `RESEARCH-001` — Deepen version-specific static playbooks while preserving the dynamic-analysis
   exclusion.

Only one task may be active at a time. Do not mark a profile complete with placeholders or mocks.
