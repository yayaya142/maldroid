# ADR 0002: Execution Threat Model for Python Scripts

## Status
Accepted

## Context
MalDroid agents frequently need to decode obfuscated payloads, decrypt strings, or extract structures from custom binary formats. A static, built-in library of transforms is insufficient because malware authors continually invent new encoding schemes. 

The most flexible solution is allowing the MalDroid agent to autonomously generate and execute Python scripts to process these payloads. However, executing LLM-generated code in the same environment as the agent is highly dangerous. The LLM could be prompt-injected by hostile evidence to write code that reads host secrets, beacons out to a C2 server, or deletes evidence.

We must decide how to isolate the execution of these dynamically generated scripts while remaining compatible with macOS and Kali Linux without requiring complex virtualization.

## Considered Options
1. **Full OS Virtualization (Docker/QEMU):** Provides strong isolation but breaks the "local, lightweight CLI" constraint. Requires root/daemon access.
2. **OS-Native Sandboxing (`sandbox-exec` / `bubblewrap`):** Strong isolation with no overhead. However, `sandbox-exec` is deprecated on macOS and poorly documented, while `bubblewrap` is Linux-only.
3. **Restricted Transform API (No Execution):** Provide a rich set of static tools (base64, XOR, AES) but no arbitrary code execution. Safe but inflexible.
4. **Subprocess with Strict Resource Limits and Path Jails:** Run a restricted `python -I` subprocess with `shell=False`, resource limits (`resource` module), strict timeouts, and read-only case directory access.

## Decision
We will implement **Option 4: Subprocess with Strict Resource Limits**, augmented by **Option 3 (Restricted Transform API)**.

We explicitly acknowledge that `subprocess` is **NOT a secure sandbox** against a determined adversary. A hostile script can still read world-readable host files or attempt local network connections if the OS allows it.

To mitigate this, we enforce:
1. **Provenance:** Every script is written to `<case_root>/scripts/` and cryptographically hashed before execution.
2. **Path Limitations:** The script is executed with its working directory set to `<case_root>/workspace/`.
3. **Execution Limits:** Strict timeouts (e.g., 5 seconds) and memory limits via the `resource` module.
4. **Data Isolation:** Scripts cannot accept evidence files as direct execution targets; they can only read them as input data.
5. **Transparency:** The `ui.py` layer will prominently warn the user that arbitrary execution is occurring.

## Consequences
- **Positive:** Agents can decode novel obfuscation dynamically without blocking the user.
- **Negative:** If a prompt injection attack succeeds, the script could potentially read host data (e.g. `~/.ssh/id_rsa`). Users analyzing highly sophisticated, hostile payloads that actively target MalDroid should use a disposable VM.
