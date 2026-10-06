"""FileInfo — facts about a single source file on disk."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileInfo:
    path: Path
    name: str
    extension: str
    format: str
    category: str
    size: int

    @property
    def exists(self) -> bool:
        return self.path.exists()
