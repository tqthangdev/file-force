"""Format registry — format metadata (FORMAT_INFO) plus the pair -> engine map.

Two different kinds of information are kept separate:

- **Capability** (what converts to what) lives in each converter's
  ``supported_pairs()``.
- **Format metadata** (facts about a format: extensions, MIME, display name,
  category) lives in the static ``FORMAT_INFO`` table.

They are not duplicates: a converter declares ``("png", "jpg")`` without having to
know that JPEG is called "JPEG" or that ``.jpeg`` is an extension of ``jpg``.
"""
from __future__ import annotations

from app.converters.base import BaseConverter

FORMAT_INFO: dict[str, dict] = {
    "png": {
        "display_name": "PNG",
        "category": "image",
        "extensions": [".png"],
        "mime": "image/png",
    },
    "jpg": {
        "display_name": "JPEG",
        "category": "image",
        "extensions": [".jpg", ".jpeg"],
        "mime": "image/jpeg",
    },
    "webp": {
        "display_name": "WebP",
        "category": "image",
        "extensions": [".webp"],
        "mime": "image/webp",
    },
    "bmp": {
        "display_name": "BMP",
        "category": "image",
        "extensions": [".bmp"],
        "mime": "image/bmp",
    },
    "tiff": {
        "display_name": "TIFF",
        "category": "image",
        "extensions": [".tif", ".tiff"],
        "mime": "image/tiff",
    },
    "ico": {
        "display_name": "ICO",
        "category": "image",
        "extensions": [".ico"],
        "mime": "image/x-icon",
    },
    "pdf": {
        "display_name": "PDF",
        "category": "document",
        "extensions": [".pdf"],
        "mime": "application/pdf",
    },
    "doc": {
        "display_name": "Word 97-2003",
        "category": "document",
        "extensions": [".doc"],
        "mime": "application/msword",
    },
    "docx": {
        "display_name": "Word",
        "category": "document",
        "extensions": [".docx"],
        "mime": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    },
    "odt": {
        "display_name": "OpenDocument Text",
        "category": "document",
        "extensions": [".odt"],
        "mime": "application/vnd.oasis.opendocument.text",
    },
    "rtf": {
        "display_name": "Rich Text",
        "category": "document",
        "extensions": [".rtf"],
        "mime": "application/rtf",
    },
    "txt": {
        "display_name": "Plain Text",
        "category": "document",
        "extensions": [".txt"],
        "mime": "text/plain",
    },
    "mp3": {
        "display_name": "MP3",
        "category": "audio",
        "extensions": [".mp3"],
        "mime": "audio/mpeg",
    },
    "wav": {
        "display_name": "WAV",
        "category": "audio",
        "extensions": [".wav"],
        "mime": "audio/wav",
    },
    "flac": {
        "display_name": "FLAC",
        "category": "audio",
        "extensions": [".flac"],
        "mime": "audio/flac",
    },
    "aac": {
        "display_name": "AAC",
        "category": "audio",
        "extensions": [".aac"],
        "mime": "audio/aac",
    },
    "ogg": {
        "display_name": "OGG",
        "category": "audio",
        "extensions": [".ogg", ".oga"],
        "mime": "audio/ogg",
    },
    "m4a": {
        "display_name": "M4A",
        "category": "audio",
        "extensions": [".m4a"],
        "mime": "audio/mp4",
    },
    "mp4": {
        "display_name": "MP4",
        "category": "video",
        "extensions": [".mp4"],
        "mime": "video/mp4",
    },
    "mkv": {
        "display_name": "MKV",
        "category": "video",
        "extensions": [".mkv"],
        "mime": "video/x-matroska",
    },
    "webm": {
        "display_name": "WebM",
        "category": "video",
        "extensions": [".webm"],
        "mime": "video/webm",
    },
    "mov": {
        "display_name": "MOV",
        "category": "video",
        "extensions": [".mov"],
        "mime": "video/quicktime",
    },
    "avi": {
        "display_name": "AVI",
        "category": "video",
        "extensions": [".avi"],
        "mime": "video/x-msvideo",
    },
}

_DEFAULT_INFO = {
    "display_name": "",
    "category": "other",
    "extensions": [],
    "mime": "application/octet-stream",
}


def normalize_format(token: str) -> str:
    token = (token or "").strip().lower()
    if token.startswith("."):
        token = token[1:]
    return {"jpeg": "jpg", "tif": "tiff"}.get(token, token)


class FormatRegistry:
    def __init__(self) -> None:
        self._converters: dict[str, BaseConverter] = {}
        self._pairs: dict[tuple[str, str], list[BaseConverter]] = {}

    # --------------------------------------------------------------- registration
    def register(self, converter: BaseConverter) -> None:
        name = converter.name
        if not name:
            raise ValueError("Converter must define a non-empty name")
        if name in self._converters:
            raise ValueError(f"Converter {name!r} is already registered")
        self._converters[name] = converter
        for pair in converter.supported_pairs():
            normalized = (normalize_format(pair[0]), normalize_format(pair[1]))
            self._pairs.setdefault(normalized, []).append(converter)
        for bucket in self._pairs.values():
            bucket.sort(key=lambda c: c.priority, reverse=True)

    # ------------------------------------------------------------------ converters
    @property
    def converters(self) -> dict[str, BaseConverter]:
        return dict(self._converters)

    def get(self, name: str) -> BaseConverter | None:
        return self._converters.get(name)

    # -------------------------------------------------------------------- metadata
    def format_info(self, fmt: str) -> dict:
        info = FORMAT_INFO.get(normalize_format(fmt))
        if info is None:
            return {**_DEFAULT_INFO, "display_name": normalize_format(fmt).upper()}
        return info

    def display_name(self, fmt: str) -> str:
        return self.format_info(fmt)["display_name"]

    def category(self, fmt: str) -> str:
        return self.format_info(fmt)["category"]

    def extensions(self, fmt: str) -> list[str]:
        return list(self.format_info(fmt)["extensions"])

    def primary_extension(self, fmt: str) -> str:
        exts = self.extensions(fmt)
        if exts:
            return exts[0].lstrip(".")
        return normalize_format(fmt)

    def known_formats(self) -> list[str]:
        return sorted(FORMAT_INFO)

    # ------------------------------------------------------------------ capability
    def supports(self, source_format: str, target_format: str) -> bool:
        return (
            normalize_format(source_format),
            normalize_format(target_format),
        ) in self._pairs

    def targets_for(self, source_format: str) -> list[str]:
        """Target formats reachable from ``source_format`` (any engine)."""
        src = normalize_format(source_format)
        targets = {t for (s, t) in self._pairs if s == src and s != t}
        return sorted(targets, key=lambda t: self.display_name(t))

    def sources(self) -> list[str]:
        return sorted({s for (s, _t) in self._pairs}, key=lambda f: self.display_name(f))

    def engines_for(self, source_format: str, target_format: str) -> list[BaseConverter]:
        """Converters for a pair, highest priority first."""
        pair = (normalize_format(source_format), normalize_format(target_format))
        return list(self._pairs.get(pair, []))

    def available_engines_for(
        self, source_format: str, target_format: str
    ) -> list[BaseConverter]:
        return [c for c in self.engines_for(source_format, target_format) if c.is_available()]

    def is_available(self, source_format: str, target_format: str) -> bool:
        return bool(self.available_engines_for(source_format, target_format))

    def disabled_reason(self, source_format: str, target_format: str) -> str | None:
        """Why a pair cannot run, or None if it can."""
        engines = self.engines_for(source_format, target_format)
        if not engines:
            return (
                f"No engine converts {self.display_name(source_format)} "
                f"to {self.display_name(target_format)}."
            )
        if any(c.is_available() for c in engines):
            return None
        for converter in engines:
            reason = converter.unavailable_reason()
            if reason:
                return reason
        return "Required conversion tool is not available."
