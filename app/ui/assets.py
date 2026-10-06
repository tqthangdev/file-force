"""Locating bundled UI assets (icons).

One place resolves the assets directory, so modules nested at different depths in
``app/ui`` cannot get the relative path wrong.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QIcon

APP_DIR = Path(__file__).resolve().parents[1]  # the `app` package
ICONS_DIR = APP_DIR / "assets" / "icons"

APP_ICON = "fileforge.ico"

_app_icon: QIcon | None = None


def icon_path(name: str) -> Path:
    """Absolute path to a bundled icon."""
    return ICONS_DIR / name


def app_icon() -> QIcon:
    """The application/window icon (loaded once)."""
    global _app_icon
    if _app_icon is None:
        path = icon_path(APP_ICON)
        _app_icon = QIcon(str(path)) if path.exists() else QIcon()
    return _app_icon
