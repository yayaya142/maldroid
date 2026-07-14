#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON:-}"

if [ -z "${PYTHON_BIN}" ] && [ -x "${VENV_DIR}/bin/python" ]; then
  PYTHON_BIN="${VENV_DIR}/bin/python"
fi

if [ -z "${PYTHON_BIN}" ]; then
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1 && \
      "${candidate}" -m ensurepip --version >/dev/null 2>&1; then
      PYTHON_BIN="${candidate}"
      break
    fi
  done
fi

if [ -z "${PYTHON_BIN}" ]; then
  echo "No Python 3.11+ interpreter with ensurepip was found." >&2
  echo "Kali/Debian: install python3-venv (or python3-full), then rerun this command." >&2
  echo "macOS: install a current Python from python.org or Homebrew, then rerun this command." >&2
  exit 1
fi

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

if [ ! -f "${VENV_DIR}/.maldroid-dev-ready" ] || [ "${ROOT_DIR}/pyproject.toml" -nt "${VENV_DIR}/.maldroid-dev-ready" ]; then
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -e "${ROOT_DIR}[dev]"
  touch "${VENV_DIR}/.maldroid-dev-ready"
fi
