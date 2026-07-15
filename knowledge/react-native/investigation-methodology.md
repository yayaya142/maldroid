---
title: React Native Investigation Methodology
profile: react-native
tags: [react-native, metro, hermes, bridge, network, storage, methodology]
last_verified: 2026-07-15
---

# React Native Investigation Methodology

## Objective

Reconstruct security-relevant behavior from very large React Native artifacts without confusing
text matches with executable data flow. Preserve exact module, line, and byte-offset evidence as
the investigation progresses.

## Artifact decision tree

1. Inventory bundle, source map, extracted JavaScript, Hermes bytecode, Hermes disassembly, and
   native Android artifacts separately.
2. Plain JavaScript or Metro: inspect the wrapper and build a module index before broad reading.
3. Binary Hermes: identify bytecode/version first. Use only a compatible static decoder or existing
   researcher-provided output; never pretend the binary is JavaScript.
4. Source map: validate that it matches the bundle before trusting names and locations.
5. Minified output: use stable literals, property names, endpoints, native-module names, and module
   relationships. Short variable names are not reliable identities.

## Investigation sequence

1. Create TODOs for artifact classification, application entrypoints, bridges, persistence,
   network behavior, sensitive collection, command handling, and verification.
2. Run metadata and bundle inspection. Index Metro modules or the large text before searching.
3. Locate bootstrap and navigation: `__r`, `AppRegistry`, root component registration, route names,
   deep links, background tasks, push handlers, and headless tasks.
4. Inventory native boundaries: `NativeModules`, TurboModules, `requireNativeComponent`, event
   emitters, Android module names, and bridge method strings. Correlate names with Java/Kotlin/JNI
   artifacts when present.
5. Trace data sources: device/application identifiers, accounts, contacts, location, clipboard,
   accessibility-derived content, notifications, files, preferences, databases, intents, and push
   payloads.
6. Trace transformations: JSON construction, encoding, compression, encryption, signing, key
   derivation, and serialization. A crypto API occurrence does not prove protection of a value.
7. Trace sinks: HTTP clients, WebSocket, WebView messaging, upload/form builders, native bridge
   calls, file writes, logs, clipboard, intents, and command dispatch.
8. Investigate control channels: polling, push/FCM handlers, WebSocket listeners, dynamic route or
   method dispatch, downloaded configuration, feature flags, and retry/backoff logic.
9. Verify each important path in both directions: from source toward sink and from sink back to the
   value producer. Record gaps explicitly.

## High-signal search families

- Network: `http://`, `https://`, `ws://`, `wss://`, `fetch`, `axios`, `XMLHttpRequest`, request
  builders, headers, tokens, certificate pinning, proxy configuration, and retry code.
- Storage: `AsyncStorage`, MMKV, SQLite, Realm, keychain/keystore wrappers, filesystem paths, and
  cached configuration.
- Android capability: accessibility, overlay, boot, notification listener, device admin, VPN,
  foreground service, package queries, intents, and permission request wrappers.
- Dynamic behavior: `eval`, `Function`, dynamic `require`, downloaded bundles, WebView JavaScript,
  reflection/native loaders, and encrypted assets. Treat these as leads until the loaded content
  and call path are established.

## Evidence and confidence

- Exact: a bounded module/range shows value construction and a direct call to the sink.
- Strong inference: source and sink are connected through a short trace with one unresolved
  framework wrapper.
- Hypothesis: related literals or APIs occur without a demonstrated path.
- Negative searches are coverage statements, not proof that behavior is absent.

Save Findings when a supported fact or labeled hypothesis appears. A checkpoint should capture
what behavior was learned, which Finding/TODO IDs changed, the remaining gap, and the next exact
trace—not the names of tools used.

## Failure recovery

- Unsupported Metro wrapper: use large-text chunk indexing and stable literals.
- No useful names: pivot through endpoints, JSON keys, bridge strings, Android component names,
  route tables, and repeated constants.
- Huge one-line minified bundle: use byte offsets/module boundaries instead of line-only citations.
- Hermes version mismatch: stop semantic decoding, record the version evidence, and request or use
  compatible static output.

## References

- https://metrobundler.dev/docs/concepts
- https://reactnative.dev/docs/native-modules-android
- https://reactnative.dev/architecture/bundled-hermes
- https://github.com/facebook/hermes
