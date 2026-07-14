"""Local file logging without investigation-data telemetry."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_case_logging(case_root: Path, debug: bool = False) -> logging.Logger:
    """Configure one case-local application log and return the package logger."""
    directory = case_root / ".maldroid" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("maldroid")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(directory / "maldroid.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    logger.info("Case logging initialized")
    return logger
