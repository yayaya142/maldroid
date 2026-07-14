"""Single source of truth for secure llama-server command construction."""

from __future__ import annotations

import secrets
import shlex
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

from maldroid.config import AppConfig
from maldroid.exceptions import ConfigurationError
from maldroid.paths import expand_path


@dataclass(frozen=True)
class ServerCommand:
    arguments: list[str]
    port: int
    api_key: str | None

    def display(self) -> str:
        redacted: list[str] = []
        hide_next = False
        for argument in self.arguments:
            if hide_next:
                redacted.append("<redacted>")
                hide_next = False
            else:
                redacted.append(argument)
                hide_next = argument == "--api-key"
        return shlex.join(redacted)


def resolve_binary(value: str) -> Path:
    candidate = expand_path(value)
    if "/" in value or candidate.exists():
        if not candidate.is_file():
            raise ConfigurationError(f"llama-server was not found: {candidate}")
        if not candidate.stat().st_mode & 0o111:
            raise ConfigurationError(f"llama-server is not executable: {candidate}")
        return candidate
    found = shutil.which(value)
    if not found:
        raise ConfigurationError("llama-server was not found. Run: maldroid config init")
    return Path(found)


def port_is_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    bind_host = host if host != "localhost" else "127.0.0.1"
    with socket.socket(family, socket.SOCK_STREAM) as handle:
        handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            handle.bind((bind_host, port))
        except OSError:
            return False
    return True


def select_port(host: str, preferred: int, explicit: bool = False) -> int:
    if port_is_free(host, preferred):
        return preferred
    if explicit:
        raise ConfigurationError(f"The requested port is already in use: {preferred}")
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    bind_host = host if host != "localhost" else "127.0.0.1"
    with socket.socket(family, socket.SOCK_STREAM) as handle:
        handle.bind((bind_host, 0))
        return int(handle.getsockname()[1])


def build_server_command(
    config: AppConfig,
    context_size: int | None = None,
    port: int | None = None,
    explicit_port: bool = False,
) -> ServerCommand:
    binary = resolve_binary(config.llama.binary)
    model = expand_path(config.llama.model)
    if not model.is_file():
        raise ConfigurationError(f"The configured model file does not exist:\n\n{model}")
    selected_port = select_port(
        config.llama.host,
        port if port is not None else config.llama.preferred_port,
        explicit=explicit_port,
    )
    api_key = secrets.token_urlsafe(32) if config.llama.api_key_enabled else None
    arguments = [
        str(binary),
        "-m",
        str(model),
        "--host",
        config.llama.host,
        "--port",
        str(selected_port),
        "-c",
        str(context_size or config.general.default_context_size),
        "--parallel",
        str(config.llama.parallel),
        "--keep",
        str(config.llama.keep),
        "-ngl",
        str(config.llama.gpu_layers),
        "-b",
        str(config.llama.batch_size),
        "--flash-attn",
        config.llama.flash_attention,
        "--jinja",
        "--no-ui",
        "--no-ui-mcp-proxy",
    ]
    if api_key:
        arguments.extend(["--api-key", api_key])
    if config.llama.chat_template_file:
        template = expand_path(config.llama.chat_template_file)
        if not template.is_file():
            raise ConfigurationError(f"Chat template file does not exist: {template}")
        arguments.extend(["--chat-template-file", str(template)])
    arguments.extend(config.llama.extra_args)
    return ServerCommand(arguments=arguments, port=selected_port, api_key=api_key)
