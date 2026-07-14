#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_ROOT="${HOME}/.local/share/maldroid"
VENV_DIR="${INSTALL_ROOT}/venv"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/maldroid"
DRY_RUN=false
DEFAULT_PACKAGE_INDEX="https://pypi.org/simple"
PACKAGE_INDEX="${MALDROID_PIP_INDEX_URL:-${DEFAULT_PACKAGE_INDEX}}"

if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=true
elif [ "$#" -gt 0 ]; then
  echo "Usage: ./install.sh [--dry-run]" >&2
  exit 2
fi

case "$(uname -s)" in
  Darwin) PLATFORM="macOS" ;;
  Linux)
    if [ -r /etc/os-release ] && grep -qi '^ID=kali' /etc/os-release; then
      PLATFORM="Kali Linux"
    elif [ -r /etc/os-release ] && grep -qiE '^(ID|ID_LIKE)=.*(debian|ubuntu)' /etc/os-release; then
      PLATFORM="Debian-compatible Linux (development compatibility)"
      echo "Warning: release acceptance targets Kali Linux; continuing on a Debian-compatible host." >&2
    else
      echo "Unsupported Linux distribution. MalDroid V1 supports Kali Linux and macOS." >&2
      exit 1
    fi
    ;;
  *) echo "MalDroid supports macOS and Kali Linux." >&2; exit 1 ;;
esac

find_python() {
  if [ -n "${PYTHON:-}" ] && [ -x "${PYTHON}" ] && \
    "${PYTHON}" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' && \
    "${PYTHON}" -m ensurepip --version >/dev/null 2>&1; then
    echo "${PYTHON}"
    return 0
  fi
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1 && \
      "${candidate}" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' && \
      "${candidate}" -m ensurepip --version >/dev/null 2>&1; then
      command -v "${candidate}"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "${PYTHON_BIN}" ]; then
  echo "Python 3.11+ with venv/ensurepip is required." >&2
  if [ "$(uname -s)" = "Linux" ]; then
    echo "Install it with: sudo apt install python3-full python3-venv" >&2
  else
    echo "Install a current Python from python.org or Homebrew." >&2
  fi
  exit 1
fi

echo "MalDroid installation plan"
echo "Platform: ${PLATFORM}"
echo "Python: ${PYTHON_BIN}"
echo "Virtual environment: ${VENV_DIR}"
echo "Executable: ${WRAPPER}"
echo "Project: ${ROOT_DIR}"
echo "ripgrep: $(command -v rg || echo 'not found (recommended)')"
echo "llama-server: $(command -v llama-server || echo 'not found; configuration will request a path')"
if [ "${PACKAGE_INDEX}" = "${DEFAULT_PACKAGE_INDEX}" ]; then
  echo "Python packages: public PyPI (isolated from user pip configuration)"
else
  echo "Python packages: custom MALDROID_PIP_INDEX_URL (isolated from user pip configuration)"
fi

if ${DRY_RUN}; then
  echo "Dry run complete; no files were changed."
  exit 0
fi

mkdir -p "${INSTALL_ROOT}" "${BIN_DIR}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"
if ! "${VENV_DIR}/bin/python" -m pip --isolated install \
  --index-url "${PACKAGE_INDEX}" --upgrade pip; then
  echo "Failed to prepare pip from the configured MalDroid package index." >&2
  echo "For an approved private mirror, set MALDROID_PIP_INDEX_URL and retry." >&2
  exit 1
fi
if ! "${VENV_DIR}/bin/python" -m pip --isolated install \
  --index-url "${PACKAGE_INDEX}" "${ROOT_DIR}"; then
  echo "Failed to install MalDroid and its Python dependencies." >&2
  echo "For an approved private mirror, set MALDROID_PIP_INDEX_URL and retry." >&2
  exit 1
fi

printf '%s\n' '#!/usr/bin/env sh' "exec \"${VENV_DIR}/bin/maldroid\" \"\$@\"" > "${WRAPPER}"
chmod 0755 "${WRAPPER}"

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *)
    LINE='export PATH="$HOME/.local/bin:$PATH"'
    echo "${BIN_DIR} is not in PATH. Add this line to your shell configuration:"
    echo "${LINE}"
    if [ -t 0 ]; then
      printf "Append it to ~/.zshrc now? [y/N] "
      read -r answer
      if [ "${answer}" = "y" ] || [ "${answer}" = "Y" ]; then
        printf '\n%s\n' "${LINE}" >> "${HOME}/.zshrc"
      fi
    fi
    ;;
esac

if [ ! -f "${HOME}/.config/maldroid/config.toml" ]; then
  "${VENV_DIR}/bin/maldroid" config init
fi
"${VENV_DIR}/bin/maldroid" doctor
echo "Installation complete."
echo "Next steps:"
echo "  maldroid --install-completion"
echo "  maldroid config validate"
echo "  maldroid mcp client-config"
echo "  maldroid --help"
