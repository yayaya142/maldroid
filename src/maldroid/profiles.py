"""Profile metadata, prompts, and lightweight artifact suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def suggest_profiles(path: Path) -> list[str]:
    names = {item.name.lower() for item in ([path] if path.is_file() else path.iterdir())}
    suggestions: list[str] = []
    if any("index.android.bundle" in name or "hermes" in name for name in names):
        suggestions.append("react-native")
    if {"libapp.so", "libflutter.so"} & names or "blutter" in names:
        suggestions.append("flutter")
    if "global-metadata.dat" in names or "libil2cpp.so" in names:
        suggestions.append("unity")
    if "config.xml" in names or "www" in names:
        suggestions.append("cordova")
    if any(name.endswith(".lua") or "cocos" in name for name in names):
        suggestions.append("cocos")
    if any(name.endswith(".so") or name.endswith(".elf") for name in names):
        suggestions.append("native")
    return suggestions
