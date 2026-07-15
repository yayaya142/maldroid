# Static Reverse Research Matrix

| Family | Artifacts | Research | Implementation | Verification |
|---|---|---|---|---|
| Android base | APK/AAB/APKS, manifest, resources, DEX | Started | Core artifact handling | Synthetic only |
| Java/Kotlin/Smali | Decompiled source and disassembly | Started | Generic bounded tools | Synthetic only |
| React Native | Metro, JS, Hermes indicators, source maps | Deep methodology and data-flow decision points | Module/bridge/behavior triage implemented | Synthetic Metro module/behavior fixture; real long run pending |
| Native | ELF, JNI, C/C++, Rust/Go binaries, Ghidra output | Deep ELF/JNI/Ghidra MCP methodology | Dependency/relocation/JNI/hardening triage implemented | Host ELF fixture; real Ghidra MCP run pending |
| Flutter | AOT libraries, assets, Blutter output | Starter playbook | Implemented | Synthetic inventory; Blutter gated |
| Unity | Mono assemblies, IL2CPP, metadata | Starter playbook | Implemented | Synthetic artifacts |
| Cordova | www, config, plugins, bridge code | Starter playbook | Implemented | Synthetic XML/JS |
| Cocos | JavaScript, Lua, compiled/encrypted scripts | Starter playbook | Implemented | Synthetic artifacts |

Research uses official framework/runtime documentation, upstream tool documentation, reputable
technical research, and benign fixtures. Every conclusion records `last_verified` and separates
exact parsing from heuristics. Dynamic-analysis material is out of scope.
