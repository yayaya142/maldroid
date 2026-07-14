"""Safe static transforms (Gate 5)."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecodeInput(Arguments):
    data: str
    encoding: Literal["base64", "hex", "xor"]
    xor_key: str | None = None


class DecodeHandler:
    def __call__(self, context: ToolContext, parsed: DecodeInput) -> str:
        try:
            if parsed.encoding == "base64":
                decoded = base64.b64decode(parsed.data)
                return decoded.decode("utf-8", errors="replace")
            elif parsed.encoding == "hex":
                decoded = bytes.fromhex(parsed.data)
                return decoded.decode("utf-8", errors="replace")
            elif parsed.encoding == "xor":
                if not parsed.xor_key:
                    return "Error: xor_key is required for XOR decoding."
                data_bytes = parsed.data.encode()
                key_bytes = parsed.xor_key.encode()
                decoded = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data_bytes)])
                return decoded.decode("utf-8", errors="replace")
            return "Unknown encoding."
        except Exception as e:
            return f"Decoding failed: {e}"


def register_transform_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="decode_data",
            description="Safely decode base64, hex, or XOR obfuscated strings.",
            profile="core",
            handler=DecodeHandler(),
            arguments_model=DecodeInput,
        )
    )
