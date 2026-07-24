# Current Handoff

Task: `PLATFORM-015`
Next task: `PLATFORM-011`

Implementation commit: the atomic `PLATFORM-015` commit containing this handoff (see `git log -1`)

## Outcome

The owner explicitly reprioritized efficient whole-code analysis, obfuscation/encoding research,
and Python decoder authoring without execution. The repository started clean and synchronized on
`main` at `cbb965d`. Baseline doctor completed with only the expected absent local llama-server/GGUF
errors, and all 197 existing tests passed before edits.

This task adds exact large-code intake, reusable contentless source indexing, focused symbol
context, encoded-literal/pipeline triage, bounded multi-stage transforms, and append-only
risk-scanned Python decoder artifacts. MalDroid does not execute those scripts, exposes no run
schema, and makes no sandbox claim. It guarantees a visible prepared/not-executed disclosure even
when a weak local model omits one. Physical Gemma 4, Apple Silicon, large proprietary source, and
owner workflow acceptance remain in `PLATFORM-011` because this Linux workspace has no configured
model or llama-server.

## Large source and context behavior

- Fenced code blocks of at least 8,192 characters are written exactly to private
  `workspace/snippets/SNIPPET-xxxx.<ext>` files before the model request. At most eight blocks and
  64 MiB per block are accepted. The active message/session receives only the surrounding request
  plus an untrusted path, language, size, and SHA-256 reference; raw code is not duplicated in
  session JSONL.
- Snippet/script/index destinations pass central case path policy and reject symlinked output
  directories. Shared artifact locks live under `.maldroid/locks`, not in the user-facing Files
  tree. Nested source symlinks are not followed.
- `MalDroid_build_code_index` atomically replaces a case-local SQLite snapshot containing source
  paths, metadata, declarations, imports, and named high-signal primitives—never source content or
  previews. `MalDroid_query_code_index` supports type/path filtering and marks returned files stale
  from indexed size/mtime. `MalDroid_read_code_context` combines exact symbol location with bounded
  adjacent lines and a match-centered minified-line preview.
- Lexical coverage now includes Java/Kotlin/Smali, C/C++/Objective-C, JavaScript/TypeScript/Vue,
  Python/Ruby/PHP, Go/Rust/Swift/Dart/C#/Scala/Groovy/Lua/Solidity, and assembly. Results remain
  triage leads, not parsed control flow or reachability proof.

## Obfuscation and transforms

- `MalDroid_analyze_obfuscation` scans bounded source chunks for Base64, hex, URL, and Unicode
  escape candidates plus Base64/character-code/URL/XOR/compression/crypto pipeline leads. It returns
  hashes, bounded decoded previews, printable ratio, entropy, confidence, and explicit heuristic
  limitations.
- `MalDroid_decode_static_chain` applies up to twelve ordered Base64/Base32/hex/URL/Unicode/ROT13,
  reverse, XOR, byte add/subtract/rotation, gzip/zlib/bzip2/LZMA stages. Every stage records
  input/output sizes and SHA-256. Final output is bounded to 2 MiB; LZMA memory is capped at 64 MiB;
  incomplete, concatenated/trailing, and expanding streams fail. Decoded bytes are never executed.
- The Android knowledge base now contains a focused obfuscation/decoder workflow that separates
  encoding, compression, transformation, and encryption; traces decoder callers/consumers; and
  defines evidence required before a Finding.

## Review-only Python decoder artifacts

- `MalDroid_write_python_script` accepts a short name, objective, source, case-relative inputs/
  expected outputs, and related state IDs. It parses source without importing it, creates a new
  private `workspace/scripts/SCRIPT-xxxx-*.py`, and writes a sibling provenance manifest.
- Manifests record creator, timestamps, model/persisted source hashes, Python/virtual-environment
  state, imported package/distribution versions where resolvable, inputs, outputs, related IDs,
  risk findings, review-only approval, null exit code, and permanent initial `not_executed` status.
  The write result separately returns a bounded unified creation diff. Overwrite is unavailable;
  every call creates a new revision.
- The best-effort AST scan refuses known process, network, native-loading, dynamic-execution,
  unsafe-deserialization, destructive, host-environment, absolute-path, and parent-traversal
  capabilities. Relative filesystem output is allowed with a review warning. This scan is not an
  isolation boundary and manual execution remains outside MalDroid policy.
- `MalDroid_list_python_scripts` and terminal `/scripts` show manifests/status without source or
  execution authority. Tool activity prints **Python decoder prepared (not executed)** immediately.
  The controller appends path, purpose, and **not executed by MalDroid** to the final answer if the
  model forgets. `MalDroid_run_python_script` is intentionally absent.

## Model/tool request composition

- The generic/React Native/Native registries now contain 53/63/63 schemas and approximately
  8,496/9,691/9,414 estimated schema tokens. The complete MCP registry, dispatcher, audit, path,
  static-only, and output policies are unchanged.
- Fast mode previously consumed all 14 positions with essential/default schemas. The default set
  is reduced from six to four, leaving objective-ranked capacity without increasing the 14/20/32
  budgets. A representative “obfuscated encrypted source + Python decoder” objective selects
  14/20/32 schemas at approximately 2,606/3,901/5,937 tokens in fast/balanced/deep; fast includes
  both obfuscation analysis and script authoring immediately.
- Catalog search synonyms now cover encrypted/decrypt/decoder/function/snippet language. Navigation
  tools do not consume objective-ranked slots but remain in the complete registry/catalog.

## Architecture and documentation

- ADR 0020 selects restricted deterministic transforms as the only autonomous decoding path and
  records write-only `PY-011`/`PY-012` behavior. Arbitrary execution, OS isolation, and escape
  acceptance remain explicitly unimplemented.
- Updated `ARCHITECTURE.md`, `SECURITY.md`, `DECISIONS.md`, `NEXT_AGENT_MASTER_PLAN.md`,
  `NEXT_STEPS.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `README.md`, `SYSTEM_PROMPT.md`, `TOOLS.md`,
  `docs/CLI.md`, `docs/WEB.md`, and the packaged Android playbook. `Tasks.MD` remains unchanged.

## Verification

Startup baseline:

- `git status --short --branch` — clean `main...origin/main` at `cbb965d`.
- `git fetch origin` and `git pull --ff-only origin main` — already up to date.
- `./scripts/dev doctor` — Python/platform/ripgrep and configured boundaries passed; expected
  errors reported the absent local llama-server and configured GGUF.
- `./scripts/dev test` — 197 passed in 4.89 seconds with one upstream Starlette/httpx2 warning.

Implementation checks completed before the final release gate:

- Initial seven-tool behavior specification — seven expected unknown-tool failures before the
  implementation.
- Focused code/research/agent/UI/MCP/Web regression set — 126 passed in 4.60 seconds.
- Transform matrix — Base32, hex, URL, Unicode escape, ROT13, reverse, XOR, byte arithmetic/
  rotation, gzip, zlib, bzip2, and LZMA all passed with provenance.
- Adversarial coverage — decompression expansion, LZMA memory policy, syntax errors, subprocess,
  network variants, `eval`, host environment, absolute/parent paths, nested/output symlinks,
  session-source leakage, script overwrite, user-facing lock clutter, and absent run schema.
- MCP protocol — generic discovery published authoring but no run tool; write executed through
  loopback MCP and produced only a `not_executed` artifact.
- `./scripts/dev lint` — Ruff passed; mypy passed for 47 source files.
- `./scripts/dev format-check` — all 63 files formatted.
- `./scripts/dev test --cov=maldroid` — 233 passed in 10.35 seconds with 78% aggregate coverage and
  one unchanged Starlette/httpx2 warning.
- Focused post-audit code/Web/UI/MCP regressions — 70 passed in 2.86 seconds. These additionally
  verify UTF-8 byte-limit enforcement, manifest-symlink refusal, and safe Web capture activity.

Final local release gate:

- `./scripts/dev python scripts/check_project_hygiene.py` — passed with no findings.
- `./scripts/dev release-check` — passed: 63 files formatted, Ruff clean, mypy clean across 47
  source files, 233 tests passed with 78% aggregate coverage, project hygiene passed, installer
  dry-run made no changes, and the wheel archive verified.
- Built `dist/maldroid-0.1.0-py3-none-any.whl`: 210,575 bytes, SHA-256
  `28dd906093238b44baa513dca1f0f49a63145ab4c7ceb1a7d97eb7b6986a910b`.
- Remote CI for this exact tree necessarily starts only after the atomic commit/push. Do not begin
  `PLATFORM-011` until the macOS 26 and Kali jobs pass; the watched run and result belong in the
  final delivery status.

## Known limitations

- No real GGUF generation ran. Schema selection is deterministic request evidence, not physical
  latency/quality acceptance. `PLATFORM-011` must verify Gemma chooses the code tools, writes valid
  source, preserves Hebrew conversation, and gives useful conclusions on the owner's real cases.
- The source index is a lexical snapshot. It does not parse scopes/types, resolve overloads,
  reconstruct control/data flow, discover files added after the snapshot, or detect same-size
  content whose mtime was deliberately restored. Rebuild after evidence changes and verify every
  lead with bounded source/tool evidence.
- Encoded-literal confidence is heuristic. High entropy does not prove encryption, and no AES/RSA/
  custom cryptographic plaintext is guessed without the required key/nonce/tag and supported data.
- Python source risk scanning can be evaded and is not a sandbox. MalDroid does not install script
  dependencies, run tests against generated source, execute scripts, or validate runtime outputs.
  A researcher who later runs a reviewed file does so with host authority outside this policy.
- Automatic paste capture applies to fenced blocks at least 8,192 characters. Unfenced large code
  should first be saved as a case file or wrapped in a Markdown fence; smaller code remains inline.
- Web shares backend capture/tools but remains BETA/held and has no dedicated script-manifest view;
  use Files/Activity or the recommended CLI `/scripts` view.
- The unchanged Starlette 1.3 warning says `TestClient` will migrate from `httpx` to `httpx2`.

## Dirty-tree and next command

Before the atomic commit, only the `PLATFORM-015` implementation, tests, knowledge, ADR, and
required technical/handoff documentation are modified. After commit/push the required state is
clean `main...origin/main`.

Exact next command after the local gate, atomic push, and successful macOS/Kali CI:

```bash
git status --short --branch && git log -5 --oneline && ./scripts/dev doctor
```

Then install/update this commit on the owner's configured macOS host and begin the CLI-focused
`PLATFORM-011` physical acceptance in `NEXT_STEPS.md`. Exercise large fenced code, the code index,
obfuscation transforms, one harmless prepared decoder, `/scripts`, and the absence of execution.
Keep Web feature work on hold.
