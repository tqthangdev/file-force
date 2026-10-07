"""Subprocess helpers: list arguments, captured output, timeouts, process trees.

Used by the FFmpeg (v0.3/v0.4) and LibreOffice (v0.2) engines. No shell strings are
ever built from user input.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)


def no_window_kwargs() -> dict:
    """Suppress the console window a subprocess would spawn on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _bundle_dir() -> str | None:
    """PyInstaller's bundle folder (``_internal`` in a onedir build), if any."""
    bundle = getattr(sys, "_MEIPASS", None)
    return str(bundle) if bundle else None


def child_env() -> dict:
    """The environment external tools should run in.

    PyInstaller puts the bundle folder first on ``LD_LIBRARY_PATH``, and child
    processes inherit it. A system tool such as ffmpeg then loads the bundle's
    copies of system libraries instead of the ones it was built against — on a
    different distribution that is an ABI mismatch ("undefined symbol"), so the
    bundle folder is removed for children. They keep the system's own libraries.
    """
    environment = dict(os.environ)
    bundle = _bundle_dir()
    if bundle is None:
        return environment

    bundle_paths = {os.path.normpath(bundle)}
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "PATH"):
        value = environment.get(var)
        if not value:
            continue
        kept = [
            entry
            for entry in value.split(os.pathsep)
            if entry and os.path.normpath(entry) not in bundle_paths
        ]
        if kept:
            environment[var] = os.pathsep.join(kept)
        else:
            environment.pop(var, None)
    return environment


def run_command(
    args: Sequence[str],
    timeout: float | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a command and capture its output. Returns the completed process.

    Does not raise on a non-zero exit code; callers inspect ``returncode``.
    """
    log.debug("run: %s", args)
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        env=child_env(),
        **no_window_kwargs(),
    )


def popen_command(args: Sequence[str], cwd: Path | None = None) -> subprocess.Popen:
    """Start a long-running process with line-buffered stdout for progress parsing."""
    log.debug("popen: %s", args)
    return subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(cwd) if cwd else None,
        env=child_env(),
        **no_window_kwargs(),
    )


def terminate_process_tree(process: subprocess.Popen, timeout: float = 5.0) -> None:
    """Terminate a process, killing its whole tree on Windows."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            **no_window_kwargs(),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
