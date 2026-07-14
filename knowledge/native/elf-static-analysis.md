---
title: Android ELF Static Analysis
profile: native
tags: [android, elf, jni, native, static]
last_verified: 2026-07-14
---

# Android ELF Static Analysis

Inspect ELF identity, architecture, endianness, sections, dynamic dependencies, exported/imported
symbols, JNI names, and printable strings. Use allowlisted `readelf`, `objdump`, `nm`, and `strings`
arguments. Save large output, search it, and read bounded disassembly ranges. Decompiled C/C++ is a
reconstruction; compiled Rust or Go may still be identified only through ELF and toolchain
artifacts. Never execute or load the library.

## References

- https://refspecs.linuxfoundation.org/elf/elf.pdf
- https://ghidra.re/ghidra_docs/
