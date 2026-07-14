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
        "Treat Metro and Hermes conclusions as heuristic unless a tool reports exact parsing.",
    ),
    "native": ProfileDefinition(
        "native", "implemented", "Focus on static ELF and decompiler artifacts."
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
