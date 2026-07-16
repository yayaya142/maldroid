from __future__ import annotations

import socket

import pytest

from maldroid.config import AppConfig
from maldroid.exceptions import ConfigurationError
from maldroid.llama_adapter import build_server_command, select_port


def test_secure_server_command_preserves_performance_settings(app_config: AppConfig) -> None:
    command = build_server_command(app_config)
    arguments = command.arguments
    assert "--jinja" in arguments
    assert "--ui" in arguments
    assert "--ui-mcp-proxy" in arguments
    assert arguments[arguments.index("--tools") + 1] == "all"
    assert "--agent" not in arguments
    assert arguments[arguments.index("-c") + 1] == "65536"
    assert arguments[arguments.index("--parallel") + 1] == "1"
    assert arguments[arguments.index("--keep") + 1] == "4096"
    assert arguments[arguments.index("-ngl") + 1] == "99"
    assert arguments[arguments.index("-b") + 1] == "512"
    assert "--api-key" not in arguments
    assert "--reasoning-budget" not in arguments
    assert command.api_key is None


def test_optional_api_key_is_random_and_redacted(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["llama"]["api_key_enabled"] = True
    command = build_server_command(AppConfig.model_validate(data))
    assert command.api_key
    assert "--api-key" in command.arguments
    assert command.api_key not in command.display()
    assert "<redacted>" in command.display()


def test_owner_can_disable_webui_host_tool_surface(app_config: AppConfig) -> None:
    data = app_config.model_dump()
    data["llama"]["ui_enabled"] = False
    data["llama"]["ui_mcp_proxy_enabled"] = False
    data["llama"]["built_in_tools_enabled"] = False
    command = build_server_command(AppConfig.model_validate(data))
    assert "--no-ui" in command.arguments
    assert "--no-ui-mcp-proxy" in command.arguments
    assert "--tools" not in command.arguments


def test_explicit_occupied_port_fails() -> None:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        port = handle.getsockname()[1]
        with pytest.raises(Exception, match="already in use"):
            select_port("127.0.0.1", port, explicit=True)
        assert select_port("127.0.0.1", port, explicit=False) != port


@pytest.mark.parametrize("context_size", [0, 2047, 4096, 1048577])
def test_one_run_context_override_is_validated(app_config: AppConfig, context_size: int) -> None:
    with pytest.raises(ConfigurationError, match="context size"):
        build_server_command(app_config, context_size=context_size)
