"""Locating the app's folders, frozen or from a source checkout.

Two different notions:

- ``app_dir()``     — the folder the app runs from; the **install target** the updater
                      replaces (the onedir bundle folder, or the repo root).
- ``resource_dir()`` — where bundled data files live. Inside a PyInstaller onedir build
                      that is ``_internal``, so ``version.json`` sits in
                      ``_internal/version.json`` (which ``verifier.version_file`` looks
                      for as well).
"""
from __future__ import annotations

import sys
from pathlib import Path

# app/core/updater/paths.py -> app/core/updater -> app/core -> app -> repo root
_SOURCE_ROOT = Path(__file__).resolve().parents[3]


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder the app runs from (the updater's install target)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _SOURCE_ROOT


def resource_dir() -> Path:
    """Folder holding bundled data files."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return _SOURCE_ROOT


def resource_path(name: str) -> Path:
    """Path to a bundled data file, e.g. ``version.json``."""
    return resource_dir() / name
