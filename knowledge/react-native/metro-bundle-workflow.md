---
title: React Native Metro Bundle Workflow
profile: react-native
tags: [react-native, metro, javascript, bundle]
last_verified: 2026-07-14
---

# React Native Metro Bundle Workflow

## Required artifacts

A Metro-style bundle, extracted JavaScript, optional source map, or decompiled Hermes output.

## Workflow

Run file metadata and bundle inspection first. If wrappers are present, build the module index.
Search exact behavior terms, endpoints, Android component names, bridge calls, or identifiers. Read
only relevant modules or bounded line ranges. Trace textual occurrences and save findings with
paths and locations.

## Limitations

Wrapper and module-ID recovery is heuristic across Metro versions and minifier output. Textual
occurrence tracing is not a runtime call graph. Source maps, when present and trustworthy, may
provide better names and locations.

## References

- https://metrobundler.dev/docs/concepts
- https://reactnative.dev/architecture/bundled-hermes

