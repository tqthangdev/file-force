"""Locating bundled UI assets (icons).

One place resolves the assets directory, so modules nested at different depths in
``app/ui`` cannot get the relative path wrong.
"""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]  # the `app` package
ICONS_DIR = APP_DIR / "assets" / "icons"


def icon_path(name: str) -> Path:
    """Absolute path to a bundled icon."""
    return ICONS_DIR / name
