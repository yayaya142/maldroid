# Built-in Tools

All tools return a `ToolResult` with `status`, `data`, optional structured `error`, `truncated`, and
`output_file`. Paths are relative to the active case. Unknown arguments are rejected. Oversized
JSON is saved under `tool-output/` and only a preview is returned.

Tools are published through the Python MCP server at the endpoint printed by `maldroid` or
`maldroid mcp serve`. MCP `tools/list` reflects the current profile dynamically. MCP `tools/call`
returns the same `ToolResult` as structured content and JSON text, with protocol `isError` set for
failed results. All calls converge on the serialized `ToolDispatcher` and its audit log.
Every public name is centrally namespaced with the `MalDroid_` prefix.

## Core tools

| Tool | Main parameters | Result | Safety boundary |
|---|---|---|---|
| `MalDroid_list_case_files` | `path`, `max_depth` | Typed bounded tree | Ignores internal/cache trees and caps entries |
| `MalDroid_get_file_info` | `path`, `calculate_hashes` | Type, MIME, size, time, binary, lines, optional SHA-256 | Hashing is opt-in |
| `MalDroid_read_file_range` | `path`, `start_line`, `end_line` | Numbered text lines | Rejects binary/unbounded reads |
| `MalDroid_search_text` | `query`, `path`, case, page options | Path, line, preview | Exact search, timeout, pagination |
| `MalDroid_search_regex` | Same search options | Bounded regex matches | Requires timeout-controlled ripgrep |
| `MalDroid_count_lines` | `path` | Streaming line count | Does not load the file |
| `MalDroid_extract_strings` | `path`, `minimum_length` | Preview and output file | Static extraction, timeout, no execution |
| `MalDroid_register_evidence` | `path`, `mode`, `calculate_hash` | Evidence record | Tool input must already be case-visible; external registration is CLI-controlled |
| `MalDroid_read_case_state` | none | Findings, TODOs, latest checkpoint, counts, and research-note digest | Complete histories use paginated list/get tools |
| `MalDroid_save_note` | text, kind, title, evidence | Stable research insight, decision, or hypothesis | Rejects tool activity, dumps, and operational errors |
| `MalDroid_save_checkpoint` | typed objective/progress/evidence/change/next-action fields | Semantic continuity record | Requires substantive content and a next action unless complete |
| `MalDroid_list_findings`, `MalDroid_get_finding` | pagination or stable ID | Complete Finding readback | No evidence bytes |
| `MalDroid_list_notes`, `MalDroid_get_note` | pagination or stable ID | Meaningful research Notes | Operational history excluded |
| `MalDroid_list_todos` | pagination | Open and completed TODOs | Stable IDs |
| `MalDroid_list_checkpoints`, `MalDroid_get_checkpoint` | pagination or stable ID | Typed research continuity | Tool/audit payloads excluded |
| `MalDroid_save_finding` | title, summary, confidence, severity, status, evidence, tags | Stable finding | Validated enums and evidence shape |
| `MalDroid_update_finding` | `finding_id`, `changes` | Updated finding | Field allowlist |
| `MalDroid_update_todo` | action, `text_or_id` | TODO or removal result | Validated actions |
| `MalDroid_search_knowledge` | `query`, `limit` | Ranked bounded excerpts | Active/generic/Android profiles only |
| `MalDroid_read_knowledge_range` | document key and line range | Numbered playbook lines | Bounded indexed document only |
| `MalDroid_index_large_text_file` | `path`, `chunk_lines` | Hash, line/chunk metadata | Text only; source is not duplicated as readable content |
| `MalDroid_search_large_text_index` | path, query, page options | Matching chunk boundaries | Contentless FTS5 |
| `MalDroid_read_large_text_chunk` | path, chunk number | Source lines/offsets and bounded content | Invalidated on source change |
| `MalDroid_inventory_case` | path and file/count limits | Types, sizes, largest files, large-text candidates | Bounded recursive inventory |
| `MalDroid_extract_network_indicators` | path and limits | URLs, WebSockets, domains, IPs, emails, source paths | Static extraction; full overflow saved |
| `MalDroid_search_behavior_patterns` | path, categories, limits | Grouped network/persistence/identity/crypto/dynamic/bridge/command/WebView leads | Bounded ripgrep or streaming fallback; matches are not reachability proof |
| `MalDroid_read_byte_range` | path, offset, length | Exact bounded hex/ASCII rows | Maximum 64 KiB |
| `MalDroid_build_research_report` | title, tentative filter | `reports/RESEARCH_REPORT.md` | Deterministic durable-state view; no evidence bytes |

Example:

```json
{
  "status": "completed",
  "data": {
    "total_matches": 731,
    "returned_matches": 25,
    "results": []
  },
  "truncated": true,
  "output_file": "tool-output/tool-20260714-234500-a1b2c3d4.json"
}
```

## React Native tools

| Tool | Main parameters | Result | Accuracy statement |
|---|---|---|---|
| `MalDroid_inspect_javascript_bundle` | `path` | Size, lines, minification, Metro/source-map/Hermes indicators | Inspection is heuristic |
| `MalDroid_index_metro_bundle` | `path` | Module offsets, start lines, IDs when recoverable | Wrapper boundaries and tail IDs are heuristic |
| `MalDroid_list_bundle_modules` | path and page options | Bounded module metadata | Requires current index |
| `MalDroid_read_bundle_module` | path, module, character limit | One bounded module | Never reads full bundle into context |
| `MalDroid_search_bundle_modules` | path, query, result/context limits | Occurrences mapped to module | Exact byte text search |
| `MalDroid_find_javascript_symbol` | same search parameters | Exact textual occurrences | Not semantic resolution |
| `MalDroid_trace_javascript_symbol_occurrences` | same search parameters | Contexts and evidence positions | Not a reconstructed runtime call graph |
| `MalDroid_extract_bundle_urls` | `path` | Unique URLs and approximate lines | Textual extraction only |
| `MalDroid_triage_react_native_bundle` | path and per-family limit | Behavior-family hits mapped to offsets and Metro modules | Leads require source-to-sink verification |
| `MalDroid_list_react_native_bridges` | path | NativeModules, TurboModules, components, offsets | Textual bridge inventory |

## Native tools

| Tool | Main parameters | Result and boundary |
|---|---|---|
| `MalDroid_inspect_elf_file` | `path` | Verified ELF header and saved `readelf -h` output |
| `MalDroid_list_elf_sections` | `path` | Saved allowlisted `readelf -W -S` output |
| `MalDroid_list_elf_symbols` | `path` | Saved allowlisted `readelf -W -s` output |
| `MalDroid_search_native_strings` | path, query, minimum length | Saved `strings` output and bounded exact matches |
| `MalDroid_read_disassembly_range` | path, hexadecimal start/stop | At most 1 MiB address range via allowlisted `objdump` |
| `MalDroid_search_disassembly` | path, query | Saved disassembly and bounded textual matches |
| `MalDroid_inspect_native_dependencies` | path | NEEDED libraries, SONAME, runpath, binding indicators |
| `MalDroid_list_elf_relocations` | path | Saved relocation inventory |
| `MalDroid_inspect_jni_surface` | path | Static JNI exports, dynamic registration indicators, Ghidra next step |
| `MalDroid_inspect_native_hardening` | path | NX, RELRO, canary, fortify indicators and source outputs |

Native inputs are parsed or disassembled statically and are never loaded or executed.

## Flutter tools

| Tool | Main parameters | Result and boundary |
|---|---|---|
| `MalDroid_inspect_flutter_artifacts` | `path` | AOT library, snapshot, asset, and symbol inventory |
| `MalDroid_check_blutter_availability` | none | Configured script presence; no execution |
| `MalDroid_run_blutter` | `libapp_path`, `output_name` | Fixed configured adapter command and saved logs/output |
| `MalDroid_search_blutter_output` | path, query | Exact search of existing textual output |
| `MalDroid_read_blutter_output_range` | path and lines | Bounded output lines |
| `MalDroid_find_dart_symbol` | path, query | Exact symbol text locations, not semantic recovery |
| `MalDroid_extract_flutter_strings` | path, minimum length | Saved static strings output |

Blutter runs only after an explicit tool request and configured path. The result always warns that
Flutter/Dart version compatibility must be verified.

## Unity tools

| Tool | Main parameters | Result and boundary |
|---|---|---|
| `MalDroid_inspect_unity_artifacts` | `path` | Managed/IL2CPP artifact inventory |
| `MalDroid_detect_unity_backend` | `path` | Mono/IL2CPP artifact indicators with heuristic certainty |
| `MalDroid_search_managed_code` | path, query | Exact search in existing C#/IL/text output |
| `MalDroid_search_il2cpp_output` | path, query | Exact search in existing C/C++/JSON/text output |
| `MalDroid_read_managed_symbol` | path, query | Bounded textual symbol locations |
| `MalDroid_read_il2cpp_symbol` | path, query | Bounded textual symbol locations |

## Cordova tools

| Tool | Main parameters | Result and boundary |
|---|---|---|
| `MalDroid_inspect_cordova_artifacts` | `path` | Config, WebView, JS, HTML, and plugin inventory |
| `MalDroid_list_cordova_plugins` | `path` | IDs and versions parsed from local XML |
| `MalDroid_search_cordova_javascript` | path, query | Exact JS/TS/HTML search |
| `MalDroid_inspect_cordova_config` | config path | Selected static XML elements and attributes |
| `MalDroid_find_cordova_bridge_usage` | `path` | Exact known JavaScript/native bridge indicators |

## Cocos tools

| Tool | Main parameters | Result and boundary |
|---|---|---|
| `MalDroid_inspect_cocos_artifacts` | `path` | JS, Lua, compiled script, and native inventory |
| `MalDroid_detect_cocos_script_type` | `path` | Extension-based type with unsupported format labels |
| `MalDroid_search_cocos_scripts` | path, query | Plaintext JS/Lua exact search only |
| `MalDroid_read_cocos_script_range` | path and lines | Bounded plaintext JS/Lua output |
| `MalDroid_extract_cocos_strings` | path, minimum length | Saved strings from compiled/static artifacts |

`/tools` and MCP discovery always display only core plus the active profile's tools.
