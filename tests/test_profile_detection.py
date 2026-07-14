from __future__ import annotations

import zipfile
from pathlib import Path

from maldroid.profile_detection import detect_profiles


def test_detects_react_native_bundle_from_name_and_bounded_content(tmp_path: Path) -> None:
    bundle = tmp_path / "index.android.bundle"
    bundle.write_text("__d(function(){return HermesInternal;},42,[]);", encoding="utf-8")

    detected = detect_profiles(tmp_path)

    assert detected.selected_profile == "react-native"
    assert detected.confidence == "high"
    assert any("Metro/Hermes" in item for item in detected.indicators["react-native"])


def test_detects_flutter_inside_apk_without_extracting_it(tmp_path: Path) -> None:
    apk = tmp_path / "sample.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("lib/arm64-v8a/libflutter.so", b"fixture")
        archive.writestr("lib/arm64-v8a/libapp.so", b"fixture")
        archive.writestr("assets/flutter_assets/AssetManifest.json", b"{}")

    detected = detect_profiles(apk)

    assert detected.selected_profile == "flutter"
    assert detected.confidence == "high"
    assert any("Archive" in item for item in detected.indicators["flutter"])


def test_framework_evidence_outranks_incidental_native_libraries(tmp_path: Path) -> None:
    (tmp_path / "global-metadata.dat").write_bytes(b"metadata")
    (tmp_path / "libil2cpp.so").write_bytes(b"\x7fELFfixture")
    for number in range(8):
        (tmp_path / f"libdependency-{number}.so").write_bytes(b"\x7fELFfixture")

    detected = detect_profiles(tmp_path)

    assert detected.selected_profile == "unity"
    assert detected.scores["native"] <= 40


def test_unknown_text_artifact_stays_generic(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("ordinary text", encoding="utf-8")

    detected = detect_profiles(tmp_path)

    assert detected.selected_profile == "generic"
    assert detected.confidence == "none"


def test_nested_external_symlink_is_not_implicitly_scanned(tmp_path: Path) -> None:
    outside = tmp_path.parent / "index.android.bundle"
    outside.write_text("__d(function() { return HermesInternal; });", encoding="utf-8")
    (tmp_path / "unregistered.bundle").symlink_to(outside)

    detected = detect_profiles(tmp_path)

    assert detected.selected_profile == "generic"

    registered = detect_profiles(tmp_path, [outside])
    assert registered.selected_profile == "react-native"
