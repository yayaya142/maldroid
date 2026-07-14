"""Lifecycle management for the local llama-server child process."""

from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from maldroid.config import AppConfig
from maldroid.exceptions import ServerError
from maldroid.llama_adapter import ServerCommand, build_server_command


class LlamaServerProcess:
    def __init__(self, config: AppConfig, case_root: Path):
        self.config = config
        self.case_root = case_root
        self.command: ServerCommand | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self._stdout: BinaryIO | None = None
        self._stderr: BinaryIO | None = None

    @property
    def base_url(self) -> str:
        if not self.command:
            raise ServerError("llama-server has not been configured.")
        host = "127.0.0.1" if self.config.llama.host == "localhost" else self.config.llama.host
        bracketed = f"[{host}]" if ":" in host else host
        return f"http://{bracketed}:{self.command.port}/v1"

    def start(
        self,
        context_size: int | None = None,
        port: int | None = None,
        explicit_port: bool = False,
    ) -> ServerCommand:
        if self.process and self.process.poll() is None:
            raise ServerError("llama-server is already running.")
        self.command = build_server_command(self.config, context_size, port, explicit_port)
        logs = self.case_root / ".maldroid" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._stdout = (logs / "llama-server.stdout.log").open("ab", buffering=0)
        self._stderr = (logs / "llama-server.stderr.log").open("ab", buffering=0)
        try:
            self.process = subprocess.Popen(
                self.command.arguments,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout,
                stderr=self._stderr,
                cwd=self.case_root,
                start_new_session=True,
            )
            self._wait_until_ready()
            return self.command
        except Exception:
            self.stop()
            raise

    def _wait_until_ready(self) -> None:
        assert self.process is not None
        assert self.command is not None
        deadline = time.monotonic() + self.config.llama.startup_timeout_seconds
        host = "127.0.0.1" if self.config.llama.host == "localhost" else self.config.llama.host
        while time.monotonic() < deadline:
            exit_code = self.process.poll()
            if exit_code is not None:
                raise ServerError(
                    "llama-server exited before becoming ready.\n\n"
                    f"Exit status: {exit_code}\n"
                    f"See: {self.case_root / '.maldroid/logs/llama-server.stderr.log'}"
                )
            try:
                connection = http.client.HTTPConnection(host, self.command.port, timeout=2)
                try:
                    connection.request("GET", "/v1/health")
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and payload.get("status") == "ok":
                        return
                finally:
                    connection.close()
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(0.25)
        raise ServerError(
            "llama-server did not become ready before the startup timeout.\n\n"
            f"See: {self.case_root / '.maldroid/logs/llama-server.stderr.log'}"
        )

    def stop(self, graceful_seconds: float = 8.0) -> None:
        process = self.process
        if process and process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=graceful_seconds)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        for handle in (self._stdout, self._stderr):
            if handle:
                handle.close()
        self.process = None
        self._stdout = None
        self._stderr = None

    def status(self) -> dict[str, object]:
        running = bool(self.process and self.process.poll() is None)
        return {
            "running": running,
            "pid": self.process.pid if running and self.process else None,
            "port": self.command.port if self.command else None,
        }

    def __enter__(self) -> LlamaServerProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
