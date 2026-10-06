"""Logging configuration: console plus a rotating log file in the user log directory."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir

APP_NAME = "FileForge"
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def log_file() -> Path:
    path = Path(user_log_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path / "fileforge.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    if root.handlers:  # already configured (e.g. tests, re-entry)
        return root

    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Could not open log file; continuing with console logging only")

    return root
