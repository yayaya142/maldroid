#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
"${ROOT_DIR}/scripts/bootstrap-dev.sh"
mkdir -p "${ROOT_DIR}/dist"
"${ROOT_DIR}/.venv/bin/python" -m pip wheel \
  "${ROOT_DIR}" \
  --no-deps \
  --wheel-dir "${ROOT_DIR}/dist"

WHEEL="$(find "${ROOT_DIR}/dist" -maxdepth 1 -type f -name 'maldroid-*.whl' -print | sort | tail -n 1)"
if [ -z "${WHEEL}" ]; then
  echo "Release wheel was not created." >&2
  exit 1
fi
echo "Release artifact: ${WHEEL}"
"${ROOT_DIR}/.venv/bin/python" -m zipfile -l "${WHEEL}" >/dev/null
echo "Wheel archive verification passed."
