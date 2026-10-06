"""FileDetector — normalize the extension and, for images, verify the real format."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.format_registry import FORMAT_INFO, normalize_format
from app.models.file_info import FileInfo

log = logging.getLogger(__name__)

# Pillow's format names mapped to our canonical tokens.
_PIL_FORMATS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "BMP": "bmp",
    "TIFF": "tiff",
    "ICO": "ico",
    "GIF": "gif",
}

# Every extension we know about, mapped to its canonical token.
_EXTENSION_MAP: dict[str, str] = {}
for _token, _info in FORMAT_INFO.items():
    for _ext in _info["extensions"]:
        _EXTENSION_MAP[_ext] = _token


class FileDetector:
    def __init__(self) -> None:
        pass

    def detect(self, path: Path) -> FileInfo:
        path = Path(path)
        ext = path.suffix.lower()
        fmt = _EXTENSION_MAP.get(ext, normalize_format(ext))

        # A PNG renamed to .jpg must be detected as PNG. Only images are probed with
        # Pillow; documents and other types are not images.
        if FORMAT_INFO.get(fmt, {}).get("category") == "image":
            real = self._real_image_format(path)
            if real:
                fmt = real

        info = FORMAT_INFO.get(fmt, {})
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        return FileInfo(
            path=path,
            name=path.name,
            extension=ext,
            format=fmt,
            category=info.get("category", "other"),
            size=size,
        )

    def detect_many(self, paths: list[Path]) -> list[FileInfo]:
        return [self.detect(p) for p in paths]

    # -------------------------------------------------------------------- helpers
    def _real_image_format(self, path: Path) -> str | None:
        try:
            with Image.open(path) as image:
                return _PIL_FORMATS.get(image.format or "")
        except (UnidentifiedImageError, OSError, ValueError):
            return None

    def supported_source(self, info: FileInfo) -> bool:
        return info.format in FORMAT_INFO
