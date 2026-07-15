"""Validated TOML configuration with secure llama-server defaults."""

from __future__ import annotations

import json
import os
import shlex
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from maldroid.constants import DEFAULT_MODEL_PATH, DEFAULT_PORT, SUPPORTED_PROFILES
from maldroid.exceptions import ConfigurationError
from maldroid.io_utils import atomic_write_text
from maldroid.paths import config_directory, default_cases_directory, expand_path

DANGEROUS_SERVER_FLAGS = {
    "--agent",
    "-ag",
}

MANAGED_SERVER_FLAGS = {
    "--tools",
    "--ui-mcp-proxy",
    "--no-ui-mcp-proxy",
    "--webui-mcp-proxy",
    "--no-webui-mcp-proxy",
    "--ui",
    "--no-ui",
    "--webui",
    "--no-webui",
}


class GeneralConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases_directory: str = str(default_cases_directory())
    default_profile: str = "generic"
    default_context_size: int = Field(default=65536, ge=2048, le=1048576)
    evidence_mode: Literal["symlink", "copy"] = "symlink"

    @field_validator("default_profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        if value not in SUPPORTED_PROFILES:
            raise ValueError(f"Unknown profile: {value}")
        return value


class LlamaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binary: str = "llama-server"
    model: str = DEFAULT_MODEL_PATH
    host: str = "127.0.0.1"
    preferred_port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    startup_timeout_seconds: int = Field(default=180, ge=1, le=3600)
    parallel: int = Field(default=1, ge=1, le=16)
    keep: int = Field(default=4096, ge=0)
    gpu_layers: int = Field(default=99, ge=0)
    batch_size: int = Field(default=512, ge=1)
    flash_attention: Literal["on", "off", "auto"] = "on"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_response_tokens: int = Field(default=4096, ge=128)
    reasoning_level: Literal["off", "low", "medium", "high", "unlimited"] = "medium"
    api_key_enabled: bool = False
    ui_enabled: bool = True
    ui_mcp_proxy_enabled: bool = True
    built_in_tools_enabled: bool = True
    chat_template_file: str | None = None
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"} and not value.endswith(".sock"):
            raise ValueError("llama-server must listen on a loopback address or Unix socket")
        return value

    @field_validator("extra_args")
    @classmethod
    def reject_unsafe_arguments(cls, value: list[str]) -> list[str]:
        for argument in value:
            flag = argument.split("=", 1)[0]
            if flag in DANGEROUS_SERVER_FLAGS:
                raise ValueError(f"Unsafe llama-server flag is forbidden: {flag}")
            if flag in MANAGED_SERVER_FLAGS:
                raise ValueError(
                    f"Set the managed llama configuration instead of extra_args: {flag}"
                )
            if flag == "--host":
                raise ValueError("Set host through the validated llama.host setting")
        return value


class LimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_tool_output_characters: int = Field(default=20000, ge=1000)
    max_search_results: int = Field(default=100, ge=1, le=10000)
    max_read_lines: int = Field(default=500, ge=1, le=10000)
    max_file_tree_entries: int = Field(default=500, ge=1, le=10000)
    command_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    max_tool_rounds: int = Field(default=8, ge=1, le=32)
    max_task_phases: int = Field(default=0, ge=0, le=100000)
    model_retry_attempts: int = Field(default=3, ge=1, le=10)
    auto_compact_ratio: float = Field(default=0.72, ge=0.5, le=0.8)
    retained_tool_results: int = Field(default=6, ge=1, le=32)


class ExternalToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blutter: str | None = None


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: Literal["127.0.0.1"] = "127.0.0.1"
    preferred_port: int = Field(default=8765, ge=1, le=65535)
    startup_timeout_seconds: int = Field(default=10, ge=1, le=60)


class WebConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    open_browser: bool = True


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    llama: LlamaConfig = Field(default_factory=LlamaConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    external_tools: ExternalToolsConfig = Field(default_factory=ExternalToolsConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    web: WebConfig = Field(default_factory=WebConfig)

    @model_validator(mode="after")
    def validate_context_budget(self) -> AppConfig:
        if self.llama.keep >= self.general.default_context_size:
            raise ValueError("llama.keep must be smaller than the context size")
        if self.llama.max_response_tokens >= self.general.default_context_size:
            raise ValueError("max_response_tokens must be smaller than the context size")
        return self


def default_config_path() -> Path:
    return config_directory() / "config.toml"


def load_config(path: Path | None = None) -> AppConfig:
    target = path or default_config_path()
    if not target.exists():
        return AppConfig()
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
        expanded = _expand_values(raw)
        return AppConfig.model_validate(expanded)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid configuration in {target}: {exc}") from exc


def _expand_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_values(item) for item in value]
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    return value


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    target = path or default_config_path()
    data = config.model_dump()
    sections: list[str] = []
    for section, values in data.items():
        sections.append(f"[{section}]")
        for key, value in values.items():
            if value is None:
                continue
            sections.append(f"{key} = {_toml_literal(value)}")
        sections.append("")
    atomic_write_text(target, "\n".join(sections), mode=0o600)
    return target


def _toml_literal(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_literal(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def set_config_value(config: AppConfig, dotted_key: str, raw_value: str) -> AppConfig:
    section, key = _validate_config_key(config, dotted_key)
    data = config.model_dump()
    current = data[section][key]
    try:
        if isinstance(current, bool):
            normalized = raw_value.lower()
            if normalized not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
                raise ValueError("expected true/false, yes/no, on/off, or 1/0")
            parsed: Any = normalized in {"1", "true", "yes", "on"}
        elif isinstance(current, int):
            parsed = int(raw_value)
        elif isinstance(current, float):
            parsed = float(raw_value)
        elif isinstance(current, list):
            parsed = shlex.split(raw_value)
        elif current is None and raw_value:
            parsed = raw_value
        else:
            parsed = raw_value
        data[section][key] = parsed
        return AppConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid value for {dotted_key}: {exc}") from exc


def get_config_value(config: AppConfig, dotted_key: str) -> Any:
    section, key = _validate_config_key(config, dotted_key)
    return config.model_dump()[section][key]


def reset_config_value(config: AppConfig, dotted_key: str) -> AppConfig:
    section, key = _validate_config_key(config, dotted_key)
    data = config.model_dump()
    defaults = AppConfig().model_dump()
    data[section][key] = defaults[section][key]
    try:
        return AppConfig.model_validate(data)
    except ValueError as exc:  # pragma: no cover - protects cross-field defaults
        raise ConfigurationError(f"Cannot reset {dotted_key}: {exc}") from exc


def _validate_config_key(config: AppConfig, dotted_key: str) -> tuple[str, str]:
    parts = dotted_key.split(".")
    if len(parts) != 2 or parts[0] not in {
        "general",
        "llama",
        "limits",
        "external_tools",
        "mcp",
        "web",
    }:
        raise ConfigurationError("Configuration keys must use section.key form.")
    data = config.model_dump()
    section, key = parts
    if key not in data[section]:
        raise ConfigurationError(f"Unknown configuration key: {dotted_key}")
    return section, key


def resolved_cases_directory(config: AppConfig) -> Path:
    return expand_path(config.general.cases_directory)
