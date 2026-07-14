---
title: Hermes Artifact Identification
profile: react-native
tags: [react-native, hermes, bytecode, versioning]
last_verified: 2026-07-14
---

# Hermes Artifact Identification

Hermes compatibility is version-sensitive and modern React Native releases bundle a corresponding
Hermes version. Record the React Native/Hermes relationship whenever it is recoverable. Distinguish
plain JavaScript, textual decompiler output, and binary bytecode. Do not claim binary parsing from
textual indicators. Unsupported bytecode should produce a compatibility warning rather than
fabricated source.

## References

- https://reactnative.dev/architecture/bundled-hermes
- https://github.com/facebook/hermes

