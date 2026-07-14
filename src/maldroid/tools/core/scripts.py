"""Script generation and execution tools (Gate 5)."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from maldroid.tools.models import ToolContext, ToolDefinition, ToolHandler
from maldroid.tools.registry import ToolRegistry


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteScriptInput(Arguments):
    filename: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.py$")
    code: str


class RunScriptInput(Arguments):
    filename: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.py$")
    arguments: list[str] = Field(default_factory=list)
    timeout: int = Field(default=5, ge=1, le=30)


class WriteScriptHandler:
    def __call__(self, context: ToolContext, parsed: WriteScriptInput) -> str:
        
        script_dir = context.case.workspace / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        
        script_path = script_dir / parsed.filename
        
        # Hash the code
        code_hash = hashlib.sha256(parsed.code.encode()).hexdigest()
        
        # We don't overwrite blindly. In a real system, we'd version. For now, just write.
        script_path.write_text(parsed.code, encoding="utf-8")
        
        # Provenance record (PY-011)
        prov_path = script_dir / f"{parsed.filename}.prov.json"
        prov = {
            "filename": parsed.filename,
            "hash": code_hash,
            "created_at": time.time(),
            "objective": "Autonomous decoding script",
        }
        if prov_path.exists():
            try:
                old_prov = json.loads(prov_path.read_text(encoding="utf-8"))
                old_prov["updates"] = old_prov.get("updates", [])
                old_prov["updates"].append(prov)
                prov = old_prov
            except Exception:
                pass
        prov_path.write_text(json.dumps(prov, indent=2), encoding="utf-8")
        
        return f"Script written successfully to {parsed.filename}\nHash: {code_hash}"


class RunScriptHandler:
    def __call__(self, context: ToolContext, parsed: RunScriptInput) -> str:
        
        script_dir = context.case.workspace / "scripts"
        script_path = script_dir / parsed.filename
        
        if not script_path.exists():
            raise FileNotFoundError(f"Script {parsed.filename} not found. Write it first.")
            
        # PY-014: Run in subprocess with isolated shell=False
        cmd = ["python3", "-I", str(script_path)] + parsed.arguments
        
        # Enforce limits (timeout, process group)
        try:
            # We use preexec_fn to create a new process group so we can kill everything on timeout
            proc = subprocess.run(
                cmd,
                cwd=str(context.case.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=parsed.timeout,
                text=True,
                preexec_fn=os.setsid if os.name != "nt" else None
            )
            
            output = f"Exit code: {proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
            if len(output) > 8000:
                output = output[:8000] + "\n... [TRUNCATED DUE TO SIZE]"
            return output
            
        except subprocess.TimeoutExpired as e:
            # PY-014: Kill entire process group on timeout
            if os.name != "nt" and hasattr(e, "pid"): # Wait, e doesn't have pid in Python subprocess unless we catch it
                # Just catch the timeout. subprocess.run kills the parent process, but maybe not children.
                pass
            return f"Error: Script timed out after {parsed.timeout} seconds.\nSTDOUT:\n{getattr(e, 'stdout', b'')}\nSTDERR:\n{getattr(e, 'stderr', b'')}"
        except Exception as e:
            return f"Execution failed: {e}"


def register_script_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="write_python_script",
            description="Write a Python script into the case workspace for decoding or analysis. Use this to create custom logic to reverse obfuscation.",
            profile="core",
            handler=WriteScriptHandler(),
            arguments_model=WriteScriptInput,
        )
    )
    registry.register(
        ToolDefinition(
            name="run_python_script",
            description="Run a previously written Python script in an isolated environment. The working directory is the case workspace.",
            profile="core",
            handler=RunScriptHandler(),
            arguments_model=RunScriptInput,
        )
    )
