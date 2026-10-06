"""Human-readable formatting helpers."""
from __future__ import annotations

from pathlib import Path

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")

# Output extensions that differ from the canonical format token.
_EXT_ALIAS = {"jpeg": "jpg", "tif": "tiff"}


def target_from_output(output: Path) -> str:
    """Canonical format token implied by an output path's extension."""
    ext = output.suffix.lstrip(".").lower()
    return _EXT_ALIAS.get(ext, ext)


def human_size(num_bytes: int | None) -> str:
    """Format a byte count for display, e.g. 2516582 -> '2.4 MB'."""
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    if size < 1000:
        return f"{int(size)} B"
    for unit in _UNITS[1:]:
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} {_UNITS[-1]}"


def format_label(fmt: str) -> str:
    """Uppercase display label for a format token, e.g. 'jpg' -> 'JPG'."""
    return fmt.upper() if fmt else "?"
