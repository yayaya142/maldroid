# Architecture Decisions

- ADR 0013: CLI and Web are presentation surfaces over one `WorkspaceRuntime`; only one global
  model workspace may run, and the Web surface is token-authenticated and loopback-only.
- ADR 0014: Self-update is explicit, fixed to the official `main` branch, temporary, globally
  exclusive, and transactional with restoration of the previous private venv on failure.

- ADR-0001: MalDroid starts and owns one local `llama-server` child for a simple daily workflow.
- ADR-0002: Tools are in-process Python handlers so policy remains independent of model behavior.
- ADR-0003: Profiles limit schemas to reduce local-model confusion and attack surface.
- ADR-0004: SQLite FTS5 is used instead of a vector database for deterministic local retrieval.
- ADR-0005: Unrestricted shell is never added to the MalDroid MCP dispatcher.
- ADR-0006: MalDroid is researcher-controlled static assistance, not an automatic APK scanner.
- ADR-0007: One sequential agent, atomic commits, and durable handoffs are the collaboration model.
- ADR-0002: MalDroid-managed tool execution uses a loopback Python MCP Streamable HTTP server.
- ADR-0008: Model API authentication is optional and off by default for direct loopback server use;
  enabling it generates a redacted random key per run.
- ADR-0009: Owner-controlled llama.cpp WebUI, MCP proxy, and built-in host tools are enabled by
  default and explicitly operate outside MalDroid MCP case policy.

Detailed records live in `docs/adr/`.
