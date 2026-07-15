# Security Model

MalDroid assumes evidence contains hostile text and binaries. Evidence cannot grant authority,
override prompts, or change tool policy.

- Bind llama-server and the Python MCP server only to loopback. Authenticate llama API calls with
  a per-session secret and enable MCP transport DNS-rebinding protection.
- Keep llama.cpp agent mode disabled. The owner-authorized loopback WebUI, MCP proxy, and built-in
  host tools are enabled by default and must be presented as unrestricted host authority outside
  MalDroid case policy and audit.
- Never expose arbitrary shell, network, deletion, overwrite, upload, or sample execution.
- Resolve lexical and real paths centrally; external symlinks require matching evidence records.
- Permit writes only inside the case, configuration, and application-data roots.
- Use argument arrays, allowlisted executables, timeouts, captured errors, and bounded outputs.
- Keep full oversized output on local disk and send only a preview to the model.
- Record tool status without secrets in `tools.jsonl`.
- Do not tunnel, proxy, or expose the MCP endpoint; a connected local client can invoke tools for
  the active case and profile until the owning process stops.
- `maldroid update` is the sole built-in network maintenance exception. It runs only when explicitly
  requested by the owner, clones the fixed official GitHub `main` branch into temporary storage,
  accepts no alternate remote/ref, uses no shell, and deletes the checkout afterward. It is outside
  evidence/tool execution and cannot overlap an active CLI or Web runtime.

Report suspected boundary bypasses privately. Do not demonstrate them on real malware or sensitive
evidence in repository tests.
