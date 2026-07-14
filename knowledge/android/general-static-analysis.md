---
title: Android General Static Analysis
profile: android
tags: [android, static, manifest, dex, resources]
last_verified: 2026-07-14
---

# Android General Static Analysis

## When to use

Use for already extracted Android manifests, resources, DEX decompiler output, Smali, native
libraries, and reports. MalDroid does not require or assume a complete APK project.

## Investigation workflow

Inventory the supplied artifacts, record provenance, inspect the manifest and exported components,
search code for those component names, identify permission-sensitive APIs, inspect endpoints and
configuration, then save evidence-backed findings. Follow control and data references in bounded
ranges. Treat decompiler output as a reconstruction that may be incomplete or incorrect.

## Common failure modes

Obfuscation, multidex separation, reflection, generated Kotlin constructs, resource indirection,
and missing native or dynamic code can hide relationships. Report absence of evidence, not evidence
of absence.

## References

- https://developer.android.com/guide/components/fundamentals
- https://source.android.com/docs/core/runtime/dalvik-bytecode

