from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from maldroid.config import (
    AppConfig,
    get_config_value,
    load_config,
    reset_config_value,
    save_config,
    set_config_value,
)


def test_default_model_performance_settings() -> None:
    config = AppConfig()
    assert config.llama.model == "~/Desktop/Tools/Ai Models/gemma-4-12B-it-qat-q4_0.gguf"
    assert config.general.default_context_size == 65536
    assert config.llama.preferred_port == 7575
    assert config.llama.parallel == 1
    assert config.llama.keep == 4096
    assert config.llama.gpu_layers == 99
    assert config.llama.batch_size == 512
    assert config.llama.flash_attention == "on"
    assert config.llama.api_key_enabled is False
    assert config.llama.ui_enabled is True
    assert config.llama.ui_mcp_proxy_enabled is True
    assert config.llama.built_in_tools_enabled is True
    assert config.limits.auto_compact_ratio == 0.72


@pytest.mark.parametrize(
    "arguments",
    [["--tools", "all"], ["--tools=all"], ["--agent"], ["--ui-mcp-proxy"]],
)
def test_dangerous_llama_flags_are_rejected(arguments: list[str]) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llama": {"extra_args": arguments}})


def test_non_loopback_host_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llama": {"host": "0.0.0.0"}})


def test_config_round_trip_and_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, app_config: AppConfig
) -> None:
    monkeypatch.setenv("MODEL_ROOT", str(tmp_path))
    data = app_config.model_dump()
    data["llama"]["model"] = "$MODEL_ROOT/model.gguf"
    config = AppConfig.model_validate(data)
    target = tmp_path / "config.toml"
    save_config(config, target)
    loaded = load_config(target)
    assert loaded.llama.model == str(tmp_path / "model.gguf")
    assert loaded.llama.chat_template_file is None
    assert loaded == set_config_value(loaded, "llama.temperature", "0.2")


def test_config_get_reset_and_invalid_values() -> None:
    changed = set_config_value(AppConfig(), "mcp.preferred_port", "9000")
    assert get_config_value(changed, "mcp.preferred_port") == 9000
    reset = reset_config_value(changed, "mcp.preferred_port")
    assert reset.mcp.preferred_port == 8765
    with pytest.raises(Exception, match="Invalid value"):
        set_config_value(AppConfig(), "general.evidence_mode", "maybe")
