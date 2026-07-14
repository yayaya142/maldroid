# Changelog

## 0.1.0 - Unreleased

- Added secure local llama-server lifecycle using the authorized Gemma 4 performance settings.
- Disabled llama.cpp UI, MCP proxy, agent mode, and built-in tools.
- Added case/evidence management, persistent investigation state, sessions, and line chat.
- Added validated core tool calling, large-file contentless FTS5, local knowledge, and React Native
  Metro tooling.
- Added static Native, Flutter, Unity, Cordova, and Cocos profile tools with bounded adapters and
  explicit compatibility reporting.
- Added automatic venv development workflow, macOS/Kali installer, safe uninstaller, documentation,
  starter playbooks, and synthetic test coverage.
- Added a loopback-only MCP Streamable HTTP server for every MalDroid tool, dynamic port reporting,
  standalone `maldroid mcp serve`, official MCP client routing for chat tools, and protocol tests.
- Made MCP port 8765 fixed by default; occupied ports now fail instead of silently falling back.
- Added a polished CLI command hierarchy, nested help, version and shell completion, documented
  configuration discovery/reset/validation, JSON automation output, MCP client-config generation,
  and reproducible wheel/release-check commands.
- Prepared public GitHub distribution metadata and replaced the user-specific model prefix with an
  equivalent home-relative default.
- Fixed cross-platform CI by normalizing ANSI help output in tests and using direct loopback HTTP
  connections that cannot inherit proxy routing.
- Pinned the macOS bootstrap to the Python 3.12 runtime selected by GitHub Actions instead of an
  unrelated preinstalled Homebrew interpreter, and upgraded Actions to their Node 24 releases.
- Made the fake llama-server integration fixture use pytest's exact Python interpreter so process
  lifecycle tests do not depend on the macOS runner's shell PATH.
