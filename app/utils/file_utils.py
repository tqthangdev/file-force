"""File path helpers: output naming, duplicate avoidance, atomic writes."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.utils.format_utils import human_size  # re-exported for convenience

__all__ = [
    "human_size",
    "unique_path",
    "build_output_path",
    "atomic_output",
    "is_subpath",
]


def unique_path(path: Path) -> Path:
    """Return a path that does not exist, appending ' (1)', ' (2)', ... if needed."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    index = 1
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def build_output_path(
    source: Path,
    output_dir: Path,
    extension: str,
    suffix: str = "",
    avoid_existing: bool = True,
) -> Path:
    """Compose the output path for a conversion.

    ``extension`` is given without a leading dot. ``suffix`` is inserted before the
    extension (e.g. '_converted'). When ``avoid_existing`` is set, an existing file is
    avoided by appending a counter.
    """
    ext = extension.lstrip(".")
    name = f"{source.stem}{suffix}.{ext}"
    candidate = output_dir / name
    if avoid_existing:
        candidate = unique_path(candidate)
    return candidate


def is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


@contextmanager
def atomic_output(target: Path, suffix: str = ".part") -> Iterator[Path]:
    """Write to a temporary sibling of ``target`` and rename on success.

    If the block raises, the temporary file is removed and ``target`` is left
    untouched — a clean failure rather than a corrupt output.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.stem}-", suffix=suffix
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        yield tmp_path
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
