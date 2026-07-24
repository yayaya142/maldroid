# Current Handoff

Task: `PLATFORM-014`
Next task: `PLATFORM-011`

Implementation commit: the atomic `PLATFORM-014` commit containing this handoff (see `git log -1`)

## Outcome

The owner put Web feature work on hold and requested a substantially faster daily CLI plus many
more static-research tools. The repository started clean and synchronized on `main` at `df75fe5`.
The baseline doctor completed with only the expected absent local llama-server/GGUF errors, and all
186 existing tests passed before edits.

This task makes the terminal the recommended surface, labels Web BETA, introduces three live CLI
speed modes, and expands the generic registry from 33 to 46 tools. It avoids the obvious regression
of sending every new schema on every model round by adding an authoritative dynamic catalog. A
representative balanced generic request now carries about 3,249 estimated schema tokens instead of
about 6,765 for the expanded full registry. It does not claim physical Gemma 4, Apple Silicon, or
Ghidra throughput acceptance because this Linux workspace has neither the configured model nor
llama-server. That remains the first work in `PLATFORM-011`.

## CLI speed and model-request composition

- `fast`, `balanced`, and `deep` are available on `maldroid cli`, `new`, `open`, and `resume` through
  `--speed`; `/speed` changes the live session and `cli.speed_mode` persists the default.
- The presets select reasoning, maximum generated tokens, and model-visible schema budgets of
  14/20/32. They never cap total phases, tool calls, or wall-clock task duration.
- Eight state/navigation schemas remain loaded. Catalog activations then take priority over a small
  default research set, and objective relevance fills remaining capacity.
- `MalDroid_search_tool_catalog` searches only the authoritative core plus active-profile registry.
  Matching internal and connected external MCP schemas are loaded for the next round. The complete
  MCP registry, dispatcher validation, path policy, audit, and output controls are unchanged.
- Measured after expansion: the complete generic/React Native/Native registries contain 46/56/56
  schemas and about 6,765/7,959/7,682 estimated tokens. For one representative generic source task,
  `fast`, `balanced`, and `deep` carried 14/20/32 schemas and about 2,282/3,249/4,801 tokens.
- `/tools` shows the complete catalog and marks what is loaded into the current model request.
  `/status`, the welcome panel, and the toolbar show the active speed.

## New bounded static-research tools

- `inspect_file`: streaming magic/type confidence, extension conflict, encoding, hashes, entropy,
  byte diversity, and head/tail characteristics in one pass.
- `inspect_archive` and `read_archive_entry`: ZIP/APK/JAR/AAB/APKS central-directory inventory,
  duplicate/encrypted/unsafe-name reporting, compression metrics, and bounded in-memory entry reads.
  Nothing is extracted or executed.
- `inspect_structured_data`: size-bounded JSON, XML, plist, INI, and YAML querying. XML uses
  defusedxml and YAML aliases are rejected for untrusted evidence.
- `inspect_sqlite`: immutable read-only schema, sample, and bounded cross-column text search. It
  exposes no arbitrary SQL or mutation path.
- `summarize_source_file`, `map_source_dependencies`, and `trace_symbol`: bounded large-source
  lexical summaries, imports/includes, definitions, high-signal calls, dependency edges, and
  symbol definition/call/assignment/reference leads.
- `compare_files` and `decode_static_value`: streamed SHA-256/first-offset comparison, bounded text
  diff, and bounded hex/Base64/URL/ROT13/single-byte-XOR decoding as data only.
- `inspect_android_manifest` and `inspect_source_map`: decoded manifest permissions/components/
  intent filters/risky declarations and bounded source-map metadata/original-source previews.
- All use the existing `PathPolicy`, Pydantic input validation, command deadlines, dispatcher
  output overflow, static-only rule, and execution audit. Lexical/static observations explicitly
  state their uncertainty.

## CLI/Web behavior and bug fix

- Bare `maldroid` now shows `1 CLI workspace (recommended)` and `2 Web workspace (BETA)`; the server
  help and Web documentation repeat the BETA status. No Web feature was added.
- CLI speed selection is intentionally not mirrored into the held Web UI. Web keeps its existing
  full active-profile request behavior; case state, MCP publication, and execution remain shared.
- `maldroid new` previously supplied its default `generic` value as though the user had explicitly
  locked the profile, disabling later automatic detection. An omitted `--profile` now remains in
  automatic mode; an actual option still creates a manual lock.

## Architecture and documentation

- ADR 0019 records per-round CLI speed presets, dynamic catalog loading, external MCP selection,
  the unchanged complete MCP registry, and the temporary BETA Web difference.
- Updated `ARCHITECTURE.md`, `DECISIONS.md`, `NEXT_AGENT_MASTER_PLAN.md`, `NEXT_STEPS.md`,
  `PROJECT_STATUS.md`, `CHANGELOG.md`, `README.md`, `SYSTEM_PROMPT.md`, `docs/CLI.md`, `docs/WEB.md`,
  and tool compatibility documentation.
- `Tasks.MD` remains unchanged as required.

## Verification

Startup baseline:

- `git status --short --branch` — clean `main...origin/main` at `df75fe5`.
- `git fetch origin && git pull --ff-only origin main` — already up to date.
- `./scripts/dev doctor` — Python/platform/ripgrep and configured boundaries passed; expected errors
  reported the absent local llama-server and configured GGUF.
- `./scripts/dev test` — 186 passed in 4.80 seconds with one upstream Starlette/httpx2 warning.

Implementation checks:

- Targeted research/config tests — passed, including file signatures, archive traversal and
  duplicate handling, bounded entry reads, YAML alias rejection, immutable SQLite, large source,
  dependencies, symbols, comparison, decoding, manifest, source map, and next-round catalog load.
- CLI help/config/tool inventory smoke checks — `--speed [fast|balanced|deep]`, Web BETA help,
  default `balanced` JSON configuration, and all 46 generic tools were present.
- Schema benchmark — full and preset counts/token estimates matched the values recorded above.
- `./scripts/dev lint` — Ruff passed; mypy passed for 45 source files.
- `./scripts/dev format-check` — all 60 files formatted.
- `./scripts/dev test` — 197 passed with one unchanged Starlette/httpx2 warning.
- `git diff --check` — passed.
- `./scripts/dev release-check` — passed: 60 files formatted, Ruff and mypy clean, 197 tests passed
  with 77% coverage, installer dry-run changed no files, wheel build/archive verification passed,
  and `dist/maldroid-0.1.0-py3-none-any.whl` was produced (188,829 bytes; SHA-256
  `f20f10dc1697f337a21921872ed91db3d24a67d7cf70fefe0e0de32c8b302fd6` on the final run).

## Known limitations

- No real GGUF generation ran, so the measured schema reduction is deterministic request-size
  evidence, not a claim that physical response time is now below a specific number of seconds.
  `PLATFORM-011` must compare all three modes on identical prompts and record prompt evaluation,
  first-token time, final time, answer quality, cache use, and Ghidra MCP selections.
- Dynamic selection is lexical. A specialized task may spend one model round searching the catalog;
  a weak model can still choose a poor tool. The system prompt gives an explicit recovery route and
  repeated unchanged catalog calls remain covered by the existing loop guard.
- Source declarations/calls/dependencies and manifest observations are lexical/static triage leads,
  not parsed reachability or control-flow proof. Binary AXML, decoded source mappings, protobuf,
  certificates/signatures, YARA, directory diff, archive extraction, and decompression remain
  incomplete or intentionally unsupported as listed in the master plan.
- Web remains BETA and on hold. Its model request still receives the complete active registry and
  therefore does not receive the CLI schema-size improvement yet.
- Starlette 1.3 emits one development-only warning that `TestClient` will migrate from `httpx` to
  `httpx2`; production behavior is unaffected.

## Dirty-tree and next command

Before the atomic commit, only the `PLATFORM-014` implementation, tests, ADR, and required technical
documentation are modified. After commit/push the required state is clean `main...origin/main`.

Exact next command after the local gate, atomic push, and successful macOS/Kali CI:

```bash
git status --short --branch && git log -5 --oneline && ./scripts/dev doctor
```

Then install/update this commit on the owner's configured macOS host and begin the CLI-focused
`PLATFORM-011` physical acceptance in `NEXT_STEPS.md`. Keep Web feature work on hold.
