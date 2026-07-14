# Current Handoff

Task: `V1-IMPLEMENTATION-001`

## Goal

Implement the MalDroid V1 foundation and React Native vertical slice from the approved plan.

## State

- Repository was created from `Tasks.MD`.
- Working implementation exists under `src/maldroid`, including every initial profile.
- Authorized model/server integration is environment-gated because this workspace lacks both the
  macOS GGUF path and `llama-server`.

## Verification

Verified in the local isolated Python 3.12 venv:

```bash
./scripts/dev format-check
./scripts/dev lint
./scripts/dev test --cov=maldroid
PYTHON="$PWD/.venv/bin/python" ./install.sh --dry-run
```

Results: Ruff formatting and lint passed; mypy passed for 32 source files; 33 tests passed; line
coverage was 66%; installer dry-run and CLI doctor/profile/tool smoke tests passed. The doctor
correctly reported that the authorized macOS model and llama-server are absent on this Linux host.

## Known limitations

- Target-platform and real-model acceptance are pending.
- Version-specific Blutter and multi-architecture external-tool fixtures need expansion.

## Next command

```bash
maldroid doctor --show-command
```

Run it on the authorized macOS host after configuring the actual llama-server binary.
