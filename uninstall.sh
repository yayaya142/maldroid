#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${HOME}/.local/share/maldroid/venv"
WRAPPER="${HOME}/.local/bin/maldroid"
CONFIG_FILE="${HOME}/.config/maldroid/config.toml"
CACHE_DIR="${HOME}/.local/share/maldroid/cache"

echo "MalDroid will remove:"
echo "  ${VENV_DIR}"
echo "  ${WRAPPER}"
echo "Cases and user knowledge will not be removed."
printf "Continue? [y/N] "
read -r answer
if [ "${answer}" != "y" ] && [ "${answer}" != "Y" ]; then
  echo "Uninstallation cancelled."
  exit 0
fi

rm -rf "${VENV_DIR}"
rm -f "${WRAPPER}"

if [ -f "${CONFIG_FILE}" ]; then
  printf "Remove configuration file ${CONFIG_FILE}? [y/N] "
  read -r answer
  if [ "${answer}" = "y" ] || [ "${answer}" = "Y" ]; then
    rm -f "${CONFIG_FILE}"
  fi
fi

if [ -d "${CACHE_DIR}" ]; then
  printf "Remove cache and global indexes ${CACHE_DIR}? [y/N] "
  read -r answer
  if [ "${answer}" = "y" ] || [ "${answer}" = "Y" ]; then
    rm -rf "${CACHE_DIR}"
  fi
fi

echo "MalDroid executable and virtual environment were removed."

