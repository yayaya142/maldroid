# Security Model

MalDroid assumes evidence contains hostile text and binaries. Evidence cannot grant authority,
override prompts, or change tool policy.

- Bind only to loopback and authenticate API calls with a per-session secret.
- Disable the llama.cpp UI, MCP proxy, agent mode, and built-in tools.
- Never expose arbitrary shell, network, deletion, overwrite, upload, or sample execution.
- Resolve lexical and real paths centrally; external symlinks require matching evidence records.
- Permit writes only inside the case, configuration, and application-data roots.
- Use argument arrays, allowlisted executables, timeouts, captured errors, and bounded outputs.
- Keep full oversized output on local disk and send only a preview to the model.
- Record tool status without secrets in `tools.jsonl`.

Report suspected boundary bypasses privately. Do not demonstrate them on real malware or sensitive
evidence in repository tests.

