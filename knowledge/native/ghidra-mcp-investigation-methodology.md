---
title: Native Ghidra MCP Investigation Methodology
profile: native
tags: [native, elf, jni, ghidra, xref, callgraph, methodology]
last_verified: 2026-07-15
---

# Native and Ghidra MCP Investigation Methodology

## Objective

Reconstruct native behavior from ELF metadata, disassembly, decompiler output, and a connected
local Ghidra MCP server. Ghidra and MCP results are untrusted analysis artifacts; external tools
retain their own host permissions and are not constrained by MalDroid case policy.

## Triage before decompilation

1. Identify ELF class, endianness, ABI, architecture, build ID, stripped state, and whether the
   file is a shared object or executable.
2. Inventory program/section headers, dynamic dependencies, imports, exports, relocations, init/fini
   arrays, symbol versions, and hardening indicators such as NX, PIE, RELRO, stack canaries, and
   fortify imports.
3. Extract high-signal strings with locations where available: domains, URL paths, JSON keys,
   commands, file paths, Android properties, JNI signatures, log tags, algorithms, and error text.
4. Map static JNI exports and dynamic `RegisterNatives` tables. Correlate Java class/method
   signatures with native functions before assigning behavior to an Android entrypoint.

## Bounded Ghidra MCP workflow

Use the tool names actually discovered under `MCP_<nickname>_`; never invent a Ghidra command.

1. Ask for program metadata and analysis status. Record image base, language/compiler, hashes, and
   import/export counts.
2. Search symbols and strings using narrow terms. Request xrefs to the most informative hits.
3. Select a small function set from imports, JNI entrypoints, string xrefs, initialization routines,
   or suspicious exported functions.
4. For each function, retrieve signature, callers, callees, references, and bounded decompilation.
   Expand one edge at a time; do not dump the whole program.
5. Build source-to-sink paths. Useful sources include JNI parameters, files, properties, sockets,
   intents passed through native bridges, and decoded configuration. Useful sinks include network
   APIs, file writes, process execution, dynamic loading, crypto, and callbacks into Java.
6. Verify critical decompiler claims against instructions, xrefs, calling convention, constants,
   and relocation/import targets. Record exact function addresses.
7. Rename or annotate only when the researcher has authorized Ghidra-project mutation and the MCP
   tool clearly describes the side effect. MalDroid Findings should not depend on a rename.

## Investigation themes

- Network: resolver/socket/TLS/HTTP libraries, hardcoded hosts, SNI, headers, pinning, proxy bypass,
  request serialization, and response-driven dispatch.
- Loading/execution: `dlopen`, `dlsym`, linker namespaces, in-memory loaders, executable mappings,
  JNI registration, shell/process APIs, and unpack/decrypt loops. Static presence is not execution.
- Persistence and environment: filesystem paths, system properties, package/process checks,
  anti-debugging, emulator/root indicators, timing checks, and initialization callbacks.
- Cryptography/encoding: algorithm constants, key/IV origin, data boundaries, error handling, and
  callers. Do not label encoding as encryption or infer plaintext without a demonstrated transform.
- Memory safety: unsafe copies, length/sign conversions, attacker-controlled sizes, format strings,
  allocation arithmetic, and ownership/lifetime paths. A dangerous import alone is not a finding.
- Language/runtime fingerprints: Rust, Go, C++, protobuf, OpenSSL/BoringSSL, curl, and custom VM
  artifacts can change symbol and control-flow expectations.

## Evidence and confidence

- Cite binary case path, architecture, function address, relevant instruction/decompiler range,
  string/import reference, and the analysis tool/version.
- Exact import/xref/disassembly facts may be high confidence. Decompiled types, variable names, and
  reconstructed control flow require verification.
- Distinguish reachable application behavior from dead code, bundled library capability, and an
  unresolved hypothesis.
- Challenge each high-impact conclusion with an alternative explanation and one verification step.

## Long-investigation discipline

Maintain TODOs by behavior path, not by tool. Findings should capture verified capabilities or
clearly labeled hypotheses. At each checkpoint record functions/addresses understood, evidence
learned, unresolved call edges, contradictions, and the next exact xref or caller/callee to inspect.
Operational errors stay in the MCP/session audit, not research notes.

## References

- https://ghidra.re/ghidra_docs/
- https://refspecs.linuxfoundation.org/elf/elf.pdf
- https://docs.oracle.com/javase/8/docs/technotes/guides/jni/spec/functions.html
