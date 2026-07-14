#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
"${ROOT_DIR}/scripts/bootstrap-dev.sh"
"${ROOT_DIR}/scripts/dev" format-check
"${ROOT_DIR}/scripts/dev" lint
"${ROOT_DIR}/scripts/dev" test --cov=maldroid
"${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/scripts/check_project_hygiene.py"
PYTHON="${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/install.sh" --dry-run
"${ROOT_DIR}/scripts/build-release.sh"
echo "MalDroid release checks passed."
