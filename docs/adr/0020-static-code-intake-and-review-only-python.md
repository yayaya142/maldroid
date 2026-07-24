# ADR 0020: Static code intake and review-only Python decoder artifacts

Status: accepted — 2026-07-24

## Context

The owner needs to give MalDroid complete source fragments and very large source trees, including
minified, encoded, obfuscated, compressed, or encrypted-looking material. Repeatedly placing that
source in local-model messages wastes context and makes a small model re-scan the same data. The
existing exact search, source summary, and one-step decoder do not provide a reusable code topology
or a provenance-rich multi-stage transform.

The owner also wants the model to write custom Python decoders, but explicitly does not want
MalDroid to run them. Python parsing, a virtual environment, import filtering, or a controlled
working directory is not a security sandbox. A generated script can access the host if a person
later runs it, so the product must not imply isolation that does not exist.

## Decision

- A fenced code block of at least 8,192 characters is captured exactly under
  `workspace/snippets/` before the model request. The active message and append-only session retain
  a short path, size, language, and SHA-256 reference instead of the source bytes. At most eight
  blocks and 64 MiB per block are accepted. Files use mode `0600`; output directories cannot be
  symbolic links. The replacement labels the source as untrusted evidence.
- `MalDroid_build_code_index` creates one replaceable case-local SQLite snapshot under
  `.maldroid/indexes/`. It stores paths, file metadata, declarations, imports, and named
  high-signal primitives, but never complete source or source previews. Nested symlinks are not
  followed. `MalDroid_query_code_index` reports stale result files, and
  `MalDroid_read_code_context` performs the later bounded evidence read.
- `MalDroid_analyze_obfuscation` detects bounded encoded literals and lexical decode/crypto/XOR/
  compression leads. `MalDroid_decode_static_chain` provides restricted deterministic transforms:
  Base64/Base32/hex/URL/Unicode escape/ROT13, reverse, XOR, byte add/subtract/rotation, and bounded
  gzip/zlib/bzip2/LZMA decompression. Every stage records input/output sizes and SHA-256. No decoded
  value is imported or executed, and decompressed output is capped at 2 MiB.
- `MalDroid_write_python_script` parses source with `ast.parse`, performs a best-effort static risk
  scan, and writes a new append-only `SCRIPT-xxxx` revision under `workspace/scripts/`. A sibling
  manifest records objective, creator, inputs, expected outputs, related state IDs, Python version,
  imports, source hashes, risk findings, timestamps, approval mode, and a permanent initial
  `not_executed` record. Script files use mode `0600`; overwrite is unavailable.
- The writer refuses known process, network, native-loading, dynamic-execution, unsafe
  deserialization, destructive, host-environment, absolute-path, and parent-traversal capabilities.
  Relative filesystem output is retained as a review warning because a useful decoder may need to
  save bytes. This scan is defense in depth and is never described as a sandbox.
- There is deliberately no `MalDroid_run_python_script` tool. The terminal `/scripts` view lists
  manifests and execution status. A successful write produces an immediate visible event, and the
  controller deterministically appends the script path, purpose, and **not executed by MalDroid**
  disclosure if the model omits it from the final answer.
- CLI speed modes keep the same 14/20/32 schema budgets. Two former default navigation schemas are
  removed from the always-loaded set, leaving objective-ranked capacity for code tools without
  increasing every prompt. Profile detection remains controller-owned and its tools remain
  available through the authoritative catalog.

This selects Gate 5 option 1—restricted built-in transforms—as the only autonomous decoding path.
It also implements case-local script provenance and write-only authoring from `PY-011`/`PY-012`.
Arbitrary execution (`PY-014`), OS isolation (`PY-015`), and escape acceptance (`PY-016`) remain
unimplemented and unauthorized.

## Consequences

Large pasted code no longer consumes every later model round, and repeated source questions can
start from one contentless index before reading only a relevant path/range. Lexical declarations,
signals, and encoded-literal confidence remain triage leads rather than parsed data flow or proof
of encryption/reachability.

A prepared script is a local review artifact, not a completed decode. MalDroid does not install its
imports, invoke Python, validate runtime behavior, or claim that manual execution is safe. A human
who chooses to run it later acts outside MalDroid's case execution policy and must first inspect the
source, inputs, outputs, dependencies, and host authority.

The complete generic catalog grows, but dynamic per-objective selection retains bounded local-model
requests. It contains 53 schemas/about 8,496 estimated tokens in full; one representative
obfuscation/decoder objective selects 14/20/32 schemas at about 2,606/3,901/5,937 tokens in
fast/balanced/deep. Web receives the shared backend capture/tool behavior; no new Web-specific UI or speed
setting is introduced while that surface remains BETA and on hold.
