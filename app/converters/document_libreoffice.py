"""LibreOfficeConverter — document conversion via headless LibreOffice.

LibreOffice is an external tool, not a Python dependency. It is invoked as a
subprocess (a list of arguments, never a shell string):

    soffice --headless --norestore --convert-to <filter> --outdir <temp> \
        -env:UserInstallation=file:///<profile> <input>

Design notes (see plan section 11):

- ``subprocess``, not UNO (``uno`` is not pip-installable and complicates packaging).
- A **separate user profile** per worker (``-env:UserInstallation``) so a running
  desktop LibreOffice cannot clash with the app.
- ``max_parallel_jobs() = 1``.
- LibreOffice names its own output, so we convert into a temp directory **inside the
  output folder** and then atomically move the produced file to the path preflight
  chose (same filesystem, so the move is atomic).
- No percentage progress: a coarse progress value is reported.
- A timeout applies to every job, and cancellation kills the whole process tree.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from platformdirs import user_cache_dir

from app.converters.base import BaseConverter, ConversionCancelled, ConversionError
from app.models.conversion_context import ConversionContext
from app.utils.format_utils import target_from_output
from app.utils.process_utils import popen_command, terminate_process_tree

log = logging.getLogger(__name__)

# Source formats this engine reads.
DOCUMENT_FORMATS = ["doc", "docx", "odt", "rtf", "txt"]
# Target formats this engine writes.
DOCUMENT_TARGETS = ["pdf", "doc", "docx", "odt", "rtf", "txt"]

# LibreOffice --convert-to filter for each target token. The explicit text filter
# pins the encoding so ``txt`` output is UTF-8 rather than the system locale.
_CONVERT_TO_FILTER = {
    "pdf": "pdf",
    "doc": "doc",
    "docx": "docx",
    "odt": "odt",
    "rtf": "rtf",
    "txt": "txt:Text (encoded):UTF8",
}

_DEFAULT_TIMEOUT = 120.0
_POLL_INTERVAL = 0.2


def default_soffice_path() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


class LibreOfficeConverter(BaseConverter):
    name = "libreoffice"
    priority = 10

    def __init__(
        self,
        resolve_path: Callable[[], str | None] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._resolve_path = resolve_path or default_soffice_path
        self.timeout = timeout
        self._profile: Path | None = None

    # ------------------------------------------------------------------ capability
    def supported_pairs(self) -> set[tuple[str, str]]:
        return {
            (src, dst)
            for src in DOCUMENT_FORMATS
            for dst in DOCUMENT_TARGETS
            if src != dst
        }

    def is_available(self) -> bool:
        return bool(self._resolve_path())

    def unavailable_reason(self) -> str | None:
        return "Document conversion needs LibreOffice. Set its path in Settings."

    def max_parallel_jobs(self) -> int:
        return 1

    # ------------------------------------------------------------------ validation
    def validate(
        self,
        source_format: str,
        target_format: str,
        source: Path,
        options: dict,
    ) -> list[str]:
        problems: list[str] = []
        if not Path(source).exists():
            problems.append("Source file not found.")
        if target_format not in _CONVERT_TO_FILTER:
            problems.append(f"LibreOffice cannot write {target_format.upper()}.")
        if not self.is_available():
            problems.append(self.unavailable_reason() or "LibreOffice is not available.")
        return problems

    # ------------------------------------------------------------------- execution
    def convert(self, context: ConversionContext) -> Path:
        executable = self._resolve_path()
        if not executable:
            raise ConversionError(self.unavailable_reason())

        target = target_from_output(context.output)
        convert_to = _CONVERT_TO_FILTER.get(target)
        if convert_to is None:
            raise ConversionError(f"LibreOffice cannot write {target.upper()}.")

        if context.cancelled:
            raise ConversionCancelled()

        context.output.parent.mkdir(parents=True, exist_ok=True)
        outdir = Path(
            tempfile.mkdtemp(dir=str(context.output.parent), prefix=".fileforge-lo-")
        )
        try:
            command = [
                executable,
                "--headless",
                "--norestore",
                "--convert-to",
                convert_to,
                "--outdir",
                str(outdir),
                f"-env:UserInstallation={self._profile_dir().as_uri()}",
                str(context.source),
            ]
            context.report(10)
            returncode, output = self._run(
                command, context.cancel_event, context.options
            )
            context.report(85)

            produced = self._find_output(outdir, context.source.stem, target)
            if produced is None:
                detail = output.strip()[:300] or "no output produced"
                raise ConversionError(
                    f"LibreOffice failed (exit {returncode}): {detail}"
                )

            os.replace(produced, context.output)
            context.report(100)
        finally:
            shutil.rmtree(outdir, ignore_errors=True)

        return context.output

    # -------------------------------------------------------------------- helpers
    def _run(
        self, command: list[str], cancel_event, options: dict
    ) -> tuple[int, str]:
        timeout = float(options.get("timeout_seconds", self.timeout))
        try:
            process = popen_command(command)
        except OSError as exc:
            raise ConversionError(f"Could not start LibreOffice: {exc}") from exc

        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel_event.is_set():
                terminate_process_tree(process)
                raise ConversionCancelled()
            if time.monotonic() > deadline:
                terminate_process_tree(process)
                raise ConversionError("LibreOffice timed out.")
            time.sleep(_POLL_INTERVAL)

        output, _ = process.communicate()
        return process.returncode, output or ""

    def _profile_dir(self) -> Path:
        # One isolated profile per converter instance (and thus per worker).
        if self._profile is None:
            profile = Path(user_cache_dir("FileForge")) / "lo-profile"
            profile.mkdir(parents=True, exist_ok=True)
            self._profile = profile
        return self._profile

    @staticmethod
    def _find_output(outdir: Path, stem: str, target: str) -> Path | None:
        for path in outdir.iterdir():
            if not path.is_file():
                continue
            if path.stem == stem and path.suffix.lower().lstrip(".") == target:
                return path
        files = [p for p in outdir.iterdir() if p.is_file()]
        return files[0] if files else None
