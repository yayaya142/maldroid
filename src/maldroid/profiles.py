"""Profile metadata and prompts."""

from __future__ import annotations

from dataclasses import dataclass

from maldroid.constants import SUPPORTED_PROFILES
from maldroid.exceptions import ConfigurationError


@dataclass(frozen=True)
class ProfileDefinition:
    name: str
    status: str
    instruction: str


PROFILES = {
    "generic": ProfileDefinition(
        "generic",
        "implemented",
        "Use only general static evidence tools and avoid framework assumptions.",
    ),
    "react-native": ProfileDefinition(
        "react-native",
        "implemented",
        "Begin with MalDroid_search_knowledge for 'React Native investigation methodology'. "
        "Classify JavaScript, Metro, Hermes, and source-map artifacts before interpreting code. "
        "For large bundles build the module index, then trace behavior across entrypoints, native "
        "bridges, storage, identity, network construction, command handling, and sensitive Android "
        "capabilities. Treat textual occurrences as leads, not data flow, and require bounded "
        "source-to-sink evidence before confirming behavior.",
    ),
    "native": ProfileDefinition(
        "native",
        "implemented",
        "Begin with MalDroid_search_knowledge for 'Native Ghidra MCP investigation methodology'. "
        "Inventory ELF architecture, hardening, imports, exports, dependencies, JNI registration, "
        "and high-signal strings before decompilation. Use connected Ghidra MCP tools in bounded "
        "steps to follow xrefs and caller/callee paths from sources to sinks. Decompiler output is "
        "a hypothesis: verify important claims against disassembly, references, and exact addresses.",
    ),
    "flutter": ProfileDefinition(
        "flutter", "implemented", "Focus on static Flutter AOT and Blutter artifacts."
    ),
    "unity": ProfileDefinition("unity", "implemented", "Distinguish Mono and IL2CPP artifacts."),
    "cordova": ProfileDefinition(
        "cordova", "implemented", "Trace static WebView and Cordova bridge artifacts."
    ),
    "cocos": ProfileDefinition(
        "cocos", "implemented", "Distinguish JavaScript, Lua, compiled, and encrypted scripts."
    ),
}


def get_profile(name: str) -> ProfileDefinition:
    if name not in SUPPORTED_PROFILES:
        raise ConfigurationError(f"Unknown profile: {name}")
    return PROFILES[name]
