---
title: Unity Static Artifact Identification
profile: unity
tags: [unity, mono, il2cpp, metadata]
last_verified: 2026-07-14
---

# Unity Static Artifact Identification

First distinguish Mono managed assemblies from IL2CPP artifacts. Managed DLLs support metadata and
decompiler workflows; IL2CPP commonly requires matching native code and metadata. Record Unity and
tool versions where recoverable. Search existing managed or IL2CPP output and read symbols in
bounded sections. Never assume one third-party tool or metadata layout works for every version.

## References

- https://docs.unity3d.com/Manual/IL2CPP.html

