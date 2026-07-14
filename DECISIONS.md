# Architecture Decisions

- ADR-0001: MalDroid starts and owns one local `llama-server` child for a simple daily workflow.
- ADR-0002: Tools are in-process Python handlers so policy remains independent of model behavior.
- ADR-0003: Profiles limit schemas to reduce local-model confusion and attack surface.
- ADR-0004: SQLite FTS5 is used instead of a vector database for deterministic local retrieval.
- ADR-0005: Unrestricted shell and llama.cpp built-in tools are forbidden.
- ADR-0006: MalDroid is researcher-controlled static assistance, not an automatic APK scanner.
- ADR-0007: One sequential agent, atomic commits, and durable handoffs are the collaboration model.

Detailed records live in `docs/adr/`.

