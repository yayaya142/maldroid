"""Bounded, evidence-backed framework detection for automatic profile selection."""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROFILE_PRIORITY = ("react-native", "flutter", "unity", "cordova", "cocos", "native")
MAX_SCANNED_FILES = 20000
MAX_CONTENT_SAMPLES = 64


@dataclass(frozen=True)
class ProfileDetection:
    selected_profile: str
    confidence: Literal["none", "low", "medium", "high"]
    scores: dict[str, int]
    indicators: dict[str, list[str]]
    scanned_files: int
    truncated: bool

    @property
    def is_actionable(self) -> bool:
        return self.selected_profile != "generic" and self.confidence in {"medium", "high"}

    def as_dict(self) -> dict[str, object]:
        return {
            "selected_profile": self.selected_profile,
            "confidence": self.confidence,
            "scores": self.scores,
            "indicators": self.indicators,
            "scanned_files": self.scanned_files,
            "truncated": self.truncated,
            "selection_policy": "highest evidence score; deterministic framework priority on ties",
        }


def detect_profiles(root: Path, extra_roots: list[Path] | None = None) -> ProfileDetection:
    """Inspect bounded names, archive entries, magic, and small content samples."""
    scores: dict[str, int] = {profile: 0 for profile in PROFILE_PRIORITY}
    indicators: dict[str, list[str]] = {profile: [] for profile in PROFILE_PRIORITY}
    scanned = 0
    content_samples = 0
    truncated = False
    seen: set[Path] = set()
    roots = [root, *(extra_roots or [])]

    def add(profile: str, points: int, indicator: str, cap: int | None = None) -> None:
        if cap is not None and scores[profile] >= cap:
            return
        scores[profile] += points
        if len(indicators[profile]) < 20 and indicator not in indicators[profile]:
            indicators[profile].append(indicator)

    for scan_root in roots:
        try:
            resolved = scan_root.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        paths = [resolved] if resolved.is_file() else _walk_files(resolved)
        for path in paths:
            if scanned >= MAX_SCANNED_FILES:
                truncated = True
                break
            # A registered root is resolved before this loop. Nested links are not evidence and
            # must never extend the detector's read boundary implicitly.
            if path.is_symlink():
                continue
            scanned += 1
            relative = _display_path(root, path)
            _score_name(relative.lower(), add)
            if path.suffix.lower() in {".apk", ".aab", ".apks", ".zip"}:
                archive_count, archive_truncated = _score_archive(path, relative, add)
                scanned += archive_count
                truncated = truncated or archive_truncated
            if content_samples < MAX_CONTENT_SAMPLES and _content_candidate(path):
                content_samples += 1
                _score_content(path, relative, add)
            if path.suffix.lower() in {".so", ".elf", ""}:
                try:
                    with path.open("rb") as handle:
                        if handle.read(4) == b"\x7fELF":
                            add("native", 8, f"ELF header: {relative}", cap=40)
                except OSError:
                    pass
        if truncated:
            break

    selected = max(PROFILE_PRIORITY, key=lambda item: (scores[item], -PROFILE_PRIORITY.index(item)))
    score = scores[selected]
    if score >= 90:
        confidence: Literal["none", "low", "medium", "high"] = "high"
    elif score >= 40:
        confidence = "medium"
    elif score > 0:
        confidence = "low"
    else:
        selected = "generic"
        confidence = "none"
    return ProfileDetection(selected, confidence, scores, indicators, scanned, truncated)


def _walk_files(root: Path):
    ignored = {".maldroid", "tool-output", "notes", "reports", ".git", ".venv"}
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name not in ignored]
        base = Path(directory)
        for name in files:
            yield base / name


def _score_name(path: str, add) -> None:
    name = Path(path).name
    parts = set(Path(path).parts)
    if name == "index.android.bundle" or "hermes" in name:
        add("react-native", 100, f"React Native bundle name: {path}")
    if name in {"libapp.so", "libflutter.so"}:
        add("flutter", 65, f"Flutter native library: {path}")
    if "flutter_assets" in parts or name in {"kernel_blob.bin", "isolate_snapshot_data"}:
        add("flutter", 90, f"Flutter asset: {path}")
    if name == "global-metadata.dat":
        add("unity", 100, f"Unity IL2CPP metadata: {path}")
    if name == "libil2cpp.so":
        add("unity", 70, f"Unity IL2CPP library: {path}")
    if name == "assembly-csharp.dll" or "managed" in parts and name.endswith(".dll"):
        add("unity", 90, f"Unity managed assembly: {path}")
    if name == "cordova.js":
        add("cordova", 100, f"Cordova runtime: {path}")
    if name == "config.xml" and "www" in parts:
        add("cordova", 55, f"Cordova web configuration: {path}")
    if "www" in parts and name == "index.html":
        add("cordova", 40, f"Packaged WebView entrypoint: {path}")
    if "cocos" in name or name == "src-settings.js":
        add("cocos", 55, f"Cocos-named artifact: {path}")
    if name.endswith((".jsc", ".luac")):
        add("cocos", 45, f"Compiled Cocos-style script: {path}")


def _content_candidate(path: Path) -> bool:
    name = path.name.lower()
    return name == "index.android.bundle" or path.suffix.lower() in {".bundle", ".js"}


def _score_content(path: Path, display: str, add) -> None:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            first = handle.read(256 * 1024)
            if size > 256 * 1024:
                handle.seek(max(0, size - 256 * 1024))
                sample = first + handle.read(256 * 1024)
            else:
                sample = first
    except OSError:
        return
    if b"__d(" in sample or b"HermesInternal" in sample:
        add("react-native", 85, f"Metro/Hermes content indicator: {display}")
    if b"cordova.define" in sample or b"cordova.require" in sample:
        add("cordova", 85, f"Cordova JavaScript indicator: {display}")
    if b"cc.game" in sample or b"cocos2d" in sample.lower():
        add("cocos", 70, f"Cocos JavaScript indicator: {display}")


def _score_archive(path: Path, display: str, add) -> tuple[int, bool]:
    try:
        if not zipfile.is_zipfile(path):
            return 0, False
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return 0, False
    selected = names[:MAX_SCANNED_FILES]
    for name in selected:
        _score_name(
            name.lower(),
            lambda profile, points, indicator, cap=None: add(
                profile, points, f"Archive {display}: {indicator}", cap
            ),
        )
    return len(selected), len(names) > len(selected)


def _display_path(case_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(case_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)
