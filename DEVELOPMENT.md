# Development

Use the managed environment; activation is unnecessary:

```bash
./scripts/dev test
./scripts/dev lint
./scripts/dev format-check
./scripts/dev maldroid --help
./scripts/dev doctor
./scripts/dev build
./scripts/dev release-check
```

`scripts/bootstrap-dev.sh` chooses Python 3.11–3.14 with working `ensurepip`, creates `.venv`, and
installs editable development dependencies. Set `PYTHON=/absolute/path/python3` to select a valid
interpreter explicitly.

Tests must not require a real model unless marked `integration`. Use temporary HOME/config/data
directories, fake model clients, fake server processes, and benign synthetic artifacts. Run
`./scripts/check_project_hygiene.py` before handoff. CI targets macOS and Kali rolling.

MCP integration tests use the official SDK client against a real loopback Streamable HTTP server.
For manual inspection, initialize a temporary case and run:

```bash
./scripts/dev maldroid mcp serve /path/to/case --json
```

`build` creates and verifies the wheel under `dist/`. `release-check` runs formatting, lint, mypy,
the complete test suite with coverage, repository hygiene, installer dry-run, and the wheel build.
