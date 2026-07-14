"""Validate mandatory handoff documents for functional changes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "PROJECT_STATUS.md",
    "NEXT_STEPS.md",
    "CHANGELOG.md",
    "docs/handoffs/CURRENT.md",
}


def changed_files() -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            changed.add(path)
    return changed


def main() -> int:
    changed = changed_files()
    functional = any(
        path.startswith(("src/", "scripts/", "install.sh", "uninstall.sh")) for path in changed
    )
    missing_files = [path for path in REQUIRED if not (ROOT / path).is_file()]
    if missing_files:
        print("Missing project governance files: " + ", ".join(sorted(missing_files)))
        return 1
    if functional:
        missing_updates = REQUIRED - changed
        if missing_updates:
            print("Functional changes require updates to: " + ", ".join(sorted(missing_updates)))
            return 1
        if not any(path.startswith("tests/") for path in changed):
            print("Functional changes require corresponding tests.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
