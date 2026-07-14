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
- Loopback model health checks explicitly bypass environment proxies; CLI help assertions are
  portable across ANSI behavior on Linux and macOS.

## Partial or environment-gated

- Real Gemma 4 tool-call verification requires the supplied macOS model and local llama-server.
- macOS, Apple Silicon, and Kali CI definitions exist but have not run in this Linux workspace.
- External-client MCP acceptance on the user's macOS client remains environment-gated.
- Installer dry-run can be validated here only as unsupported Ubuntu behavior; target smoke tests
  remain required on macOS and Kali.

## Missing later gates

- Full compatibility fixture matrix for version-dependent third-party static tools.
- A release tag after target-platform and real-model acceptance.

## Current test status

The local synthetic suite passes. See `docs/handoffs/CURRENT.md` for exact commands and counts.

## Immediate task

Run target-platform acceptance with the authorized Gemma 4 model, then expand compatibility fixtures.
