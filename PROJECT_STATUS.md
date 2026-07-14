# Project Status

Last updated: 2026-07-14

## Completed

- Governance, sequential-agent handoff contract, automatic development venv, packaging, and CI.
- Validated secure configuration with the supplied Gemma 4 performance preset.
- Managed and existing-directory cases, evidence symlink/copy, registry, resume, and case listing.
- Persistent findings, notes, TODOs, sessions, summaries, and schema versions.
- Secure llama-server command construction, port policy, ephemeral API key, logging, health, and
  shutdown lifecycle.
- Local normalized model client, reasoning-content preservation, bounded tool loop, and line chat.
- Core tool registry/dispatcher, path enforcement, audit, truncation, large-text FTS5, and knowledge.
- Loopback MCP Streamable HTTP discovery and execution for all tools, standalone serving, fixed-port
  reporting, active-profile filtering, and internal chat routing through the official client. Port
  8765 is stable by default and collisions fail without fallback.
- React Native inspection, Metro module indexing, bounded module reads, symbol search, and URLs.
- Static Native, Flutter, Unity, Cordova, and Cocos handlers with allowlisted adapters, artifact
  detection, bounded search/read operations, and explicit unsupported-format reporting.
- macOS/Kali installer design, safe uninstaller, starter documentation, and synthetic tests.
- Complete CLI discovery and automation surface: nested help, version/completion, explained config
  tables, get/set/reset/validate/path, consistent JSON output, MCP connector generation, and a
  reproducible wheel/release-check workflow.
- Public distribution metadata targets `yayaya142/maldroid`; local defaults do not expose a macOS
  account name.
- Loopback model health checks use direct HTTP connections without proxy routing; CLI help
  assertions are portable across ANSI behavior on Linux and macOS.
- GitHub macOS CI now uses the declared setup-python 3.12 runtime deterministically; Kali uses its
  rolling distribution Python.
- Cross-platform process lifecycle tests launch their fake server with pytest's exact interpreter,
  avoiding runner-specific `env python3` resolution.
- GitHub Actions uses macOS 26 explicitly so the tested environment matches the current target
  release and future OS upgrades remain deliberate.
- Process termination and direct loopback health behavior have independent deterministic tests;
  neither test depends on nested listener availability in hosted CI.
- The last completed GitHub Actions baseline passed on macOS 15 with Python 3.12 and Kali rolling,
  including lint, formatting, the complete test suite, and installer dry-run. macOS 26 validation
  is active for the current change.

## Partial or environment-gated

- Real Gemma 4 tool-call verification requires the supplied macOS model and local llama-server.
- A physical Apple Silicon smoke test remains pending; hosted macOS 26 is the current CI target.
- External-client MCP acceptance on the user's macOS client remains environment-gated.
- Installer dry-run passes in hosted macOS and Kali; real install/uninstall smoke tests remain
  required on the user's target machines.

## Missing later gates

- Full compatibility fixture matrix for version-dependent third-party static tools.
- A release tag after target-platform and real-model acceptance.

## Current test status

The local synthetic suite passes. See `docs/handoffs/CURRENT.md` for exact commands and counts.

## Immediate task

Run target-platform acceptance with the authorized Gemma 4 model, then expand compatibility fixtures.
