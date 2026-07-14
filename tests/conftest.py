from __future__ import annotations

from pathlib import Path

import pytest

from maldroid.config import AppConfig


@pytest.fixture
def app_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("MALDROID_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MALDROID_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MALDROID_CASES_DIR", str(tmp_path / "cases"))
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF-test")
    server = tmp_path / "llama-server"
    server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    server.chmod(0o755)
    return AppConfig.model_validate(
        {
            "general": {
                "cases_directory": str(tmp_path / "cases"),
                "default_profile": "generic",
                "default_context_size": 65536,
                "evidence_mode": "symlink",
            },
            "llama": {"binary": str(server), "model": str(model)},
        }
    )
