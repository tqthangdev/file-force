"""Detection of external, system-level tools (FFmpeg, LibreOffice).

Python dependencies (Pillow, PyQt6) are part of the app's environment and are not
detected here. External tools are optional: a missing tool disables only the
conversions that need it.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.services.settings import Settings

FFMPEG = "ffmpeg"
LIBREOFFICE = "libreoffice"

_WINDOWS_LIBREOFFICE_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


@dataclass
class ToolInfo:
    key: str
    name: str
    path: str | None = None
    source: str = ""  # "settings" | "PATH" | "default"

    @property
    def available(self) -> bool:
        return bool(self.path)


class ExternalTools:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tools: dict[str, ToolInfo] = {
            FFMPEG: ToolInfo(FFMPEG, "FFmpeg"),
            LIBREOFFICE: ToolInfo(LIBREOFFICE, "LibreOffice"),
        }

    # ---------------------------------------------------------------- detection
    def detect_all(self) -> None:
        self.detect(FFMPEG)
        self.detect(LIBREOFFICE)

    def detect(self, key: str) -> ToolInfo:
        tool = self.tools[key]
        manual = self._manual_path(key)
        if manual:
            tool.path, tool.source = manual, "settings"
        elif key == FFMPEG:
            found = shutil.which("ffmpeg")
            tool.path, tool.source = (found, "PATH") if found else (None, "")
        else:
            tool.path, tool.source = self._detect_libreoffice()
        return tool

    def _manual_path(self, key: str) -> str | None:
        candidate = (
            self.settings.ffmpeg_path if key == FFMPEG else self.settings.libreoffice_path
        )
        if candidate and Path(candidate).exists():
            return candidate
        return None

    def _detect_libreoffice(self) -> tuple[str | None, str]:
        for name in ("soffice", "libreoffice"):
            found = shutil.which(name)
            if found:
                return found, "PATH"
        for candidate in _WINDOWS_LIBREOFFICE_PATHS:
            if Path(candidate).exists():
                return candidate, "default"
        return None, ""

    # ------------------------------------------------------------------ queries
    def get(self, key: str) -> ToolInfo:
        return self.tools[key]

    def available(self, key: str) -> bool:
        return self.tools[key].available

    def set_manual_path(self, key: str, path: str) -> ToolInfo:
        if key == FFMPEG:
            self.settings.ffmpeg_path = path
        else:
            self.settings.libreoffice_path = path
        return self.detect(key)
