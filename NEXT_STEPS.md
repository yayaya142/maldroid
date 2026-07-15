# Ordered Next Steps

The owner has reprioritized reliability and research quality. Follow
`NEXT_AGENT_MASTER_PLAN.md`; do not add broad new tools before the durable-state gate is trustworthy.

Completed out of sequence by explicit owner reprioritization: `MODEL-010` adds enabled-by-default
streaming repetition detection, clean-session recovery with bounded carry-over, CLI/Web activity,
and the Web Settings toggle. Physical Gemma tuning is included in `PLATFORM-011`.

Completed out of sequence by explicit owner reprioritization: `WEB-002` fixes the hidden chat
composer, adds persistent Light Mode, upgrades Files navigation, and makes sidebar collapse fully
reversible. Physical active-model/browser acceptance remains in `PLATFORM-011`.

Completed out of sequence by explicit owner reprioritization: `WEB-003` replaces fixed Web widths
with a responsive 100%-zoom grid and compact-screen drawers for Projects and the full inspector.
Physical active-model acceptance remains in `PLATFORM-011`.

1. `PLATFORM-011` — Install the long-investigation and Web-workspace upgrade on the owner's macOS
   host. Verify `maldroid` mode selection, `maldroid server`, exclusive CLI/Web locking, project
   creation/switching, Hebrew input/output RTL, settings, bounded file preview, live activity,
   reports, external Ghidra MCP, and shutdown. From the installed version, run `maldroid update`,
   verify the reported commit and absence of a retained clone, then continue the long-run tests. Run a minimum
   one-hour React Native investigation and one Native/Ghidra MCP investigation. Record context
   usage across phases, pruned-result receipts, checkpoint contents, Findings/TODO/report parity,
   direct CLI triage latency, Ghidra connector tool names, model/server versions, and any repeated
   or low-value state. Acceptance: a fresh session resumes from MCP state without chat history and
   `reports/RESEARCH_REPORT.md` is useful without manual cleanup. Confirm `/triage` uses ripgrep on
   the configured Mac when present and the streaming fallback when it is absent.
2. `REL-010` — Retest the fixed `MalDroid_save_finding` path on the owner's macOS case. Record
   the structured tool call/result, case state before/after, rendered Markdown, audit/session events,
   installed commit, and model/server versions. Add a benign regression test that fails for the
   same payload shape if a distinct failure remains.
3. `REL-011` — Define canonical-state, transaction, revision, idempotency, rendering, and recovery
   invariants in an ADR with executable contract tests.
4. `REL-012` through `REL-020` — Execute the durable-state reliability chain in the exact dependency
   order documented by the master plan.
5. `STATE-010`, `STATE-011`, `STATE-012`, `STATE-014`, and `STATE-016` — Partially implemented by
   `PLATFORM-010`: typed checkpoints, record separation, low-value rejection, checkpoint UI, and
   evidence-aware final enforcement exist. Finish record linking, telemetry, revision semantics,
   and adversarial long-run acceptance in dependency order after `REL-011`.
6. `WEB-001` — Completed locally: shared CLI/Web runtime, exclusive process lease, authenticated
   loopback Web server, project conversations, chat/activity streaming, bounded Files, research
   state/actions, settings, MCP connectors, and per-message RTL. Physical macOS/model acceptance is
   folded into `PLATFORM-011`.
7. `CLI-010` — Completed: `maldroid cases` opens the configured cases directory while preserving
   `--list` and `--json` automation behavior.
8. `CLI-011` — Completed locally: `maldroid update` downloads the official `main` branch into a
   temporary checkout, transactionally replaces the private venv, rolls back failures, preserves
   user state, and deletes the checkout. Physical installed-macOS acceptance remains in
   `PLATFORM-011`.
9. `REL-001` — After the reliability gates, on the user's macOS host run installer dry-run, installation, doctor command
   preview, and `doctor --model-tool-test` using the authorized Gemma 4 GGUF. Record llama.cpp
   version and `/props` template behavior. Acceptance: structured array/object tool call and final
   response pass through MalDroid MCP independently of WebUI built-ins. Connect an external MCP client to the printed endpoint,
   confirm the saved fixed `http://127.0.0.1:8765/mcp` endpoint reconnects across runs, list tools,
   and call `MalDroid_read_case_state`. Install the generated wheel, enable zsh completion, and smoke-test
   `--help`, `config validate`, `doctor --json`, and `mcp client-config`.
   Verify the public clone from `https://github.com/yayaya142/maldroid.git` in a clean directory.
   Confirm installation succeeds despite unrelated global `pip` index configuration; use
   `MALDROID_PIP_INDEX_URL` only when an approved private mirror is intentionally required.
   Verify `SYSTEM_PROMPT.md` in one direct external-client session and confirm the model starts with
   `MalDroid_read_case_state` and `MalDroid_list_case_files` before bounded evidence reads.
   Confirm the llama.cpp UI connects without an API key under the default configuration, then
   enable `llama.api_key_enabled` once and verify the authenticated managed-client path.
   In WebUI, verify the owner can select built-in tools and that `doctor` labels their host-level
   shell and file authority clearly. After upgrading the installed package, verify that the
   automatically started MCP endpoint connects from the WebUI at `/mcp` with no second terminal,
   both directly and with the per-connection proxy enabled. Run one evidence-inspection turn and
   confirm a typed durable checkpoint appears even if the model initially omits
   `MalDroid_save_checkpoint`;
   lower `limits.auto_compact_ratio` temporarily and confirm automatic compaction resumes from it.
   Exercise the terminal workspace in macOS Terminal: command/profile completion, Alt+Enter,
   persistent history, Ctrl+C cancellation, live tool reporting, `/context`, `/reasoning` changes,
   and Ctrl+D cleanup. Confirm Gemma 4 returns separated `reasoning_content` at medium and high.
   Run an investigation exceeding eight tool rounds and verify it visibly rolls into phase 2 without
   returning to the prompt or compacting while substantial context remains. Confirm TODOs,
   evidence-backed Findings, and meaningful synthesis notes update during the run rather than only
   at completion. Confirm streamed token/context telemetry moves during generation and a
   deliberately invalid evidence path exposes the real MCP tool error. Lower the context threshold
   and verify an active task compacts and continues before its eight-round window completes.
   Test automatic profile selection with a real Metro bundle and extracted APK, then verify a mixed
   framework/native tree selects the framework, updates the toolbar, and exposes its profile tools
   without asking the user. Verify `/profile native` locks and `/profile auto` resumes detection.
   Add one real local Streamable HTTP connector and one legacy SSE connector, restart MalDroid,
   verify their `MCP_<nickname>_` tools appear and execute, then confirm an offline saved connector
   warns without blocking startup and survives a default uninstall/reinstall.
10. `REL-002` — Run the full suite and installer lifecycle on Kali rolling and Apple Silicon.
11. `COMPAT-001` — Expand benign multi-architecture ELF and versioned Blutter fixtures on target
   platforms and record exact external-tool versions.
12. `RESEARCH-001` — Deepen version-specific static playbooks according to Gate 9 of the master plan while preserving the dynamic-analysis
   exclusion.

Only one task may be active at a time. Do not mark a profile complete with placeholders or mocks.
