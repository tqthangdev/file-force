"""Application settings, persisted as JSON in the per-user config directory."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "FileForge"


def max_supported_workers() -> int:
    """Upper bound for parallel workers: the machine's CPU count.

    Conversions are CPU-bound, so more workers than cores only oversubscribe the CPU.
    """
    return max(1, os.cpu_count() or 1)


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "settings.json"


class OutputMode(str, Enum):
    SAME_FOLDER = "same_folder"
    CUSTOM_FOLDER = "custom_folder"
    CUSTOM_SUBFOLDER = "custom_subfolder"


class ConflictMode(str, Enum):
    ASK = "ask"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"


class ImagePdfMode(str, Enum):
    """What an image conversion to PDF produces."""

    SINGLE = "single"  # one PDF per image (default)
    MERGE = "merge"  # every queued image becomes a page of one PDF


@dataclass
class Settings:
    output_mode: str = OutputMode.SAME_FOLDER.value
    output_directory: str = str(Path.home() / "Downloads" / "Converted")
    output_subfolder: str = "converted"
    output_suffix: str = ""
    conflict_mode: str = ConflictMode.RENAME.value
    max_workers: int = 2
    recursive_import: bool = True
    theme: str = "system"
    image_pdf_mode: str = ImagePdfMode.SINGLE.value
    ffmpeg_path: str = ""
    libreoffice_path: str = ""

    # ---------------------------------------------------------------- persistence
    @classmethod
    def load(cls) -> "Settings":
        path = config_file()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        config_file().write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ helpers
    def output_dir_for(self, source: Path) -> Path:
        """Resolve the output directory for a source file, before naming."""
        mode = self.output_mode
        if mode == OutputMode.SAME_FOLDER.value:
            return source.parent
        if mode == OutputMode.CUSTOM_SUBFOLDER.value:
            return source.parent / self.output_subfolder
        return Path(self.output_directory)

    def clamps(self) -> None:
        self.max_workers = max(1, min(max_supported_workers(), int(self.max_workers)))
        if self.image_pdf_mode not in {mode.value for mode in ImagePdfMode}:
            self.image_pdf_mode = ImagePdfMode.SINGLE.value
