"""Shared FFmpeg subprocess handling for the audio and video engines.

FFmpeg is run as a subprocess (a list of arguments, never a shell string). Progress is
parsed from ``-progress pipe:1`` on a background reader thread so that cancellation and
timeout checks are never blocked by a quiet pipe.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from app.converters.base import ConversionCancelled, ConversionError
from app.models.conversion_context import ConversionContext
from app.utils.process_utils import popen_command, terminate_process_tree

_POLL_INTERVAL = 0.2
_TAIL_LINES = 20

AUDIO_FORMATS = ["mp3", "wav", "flac", "aac", "ogg", "m4a"]
VIDEO_FORMATS = ["mp4", "mkv", "webm", "mov", "avi"]


def parse_clock(value: str) -> float | None:
    """Parse 'HH:MM:SS.ffffff' into seconds."""
    value = value.strip()
    if not value or value.upper().startswith("N/A"):
        return None
    try:
        parts = [float(part) for part in value.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def parse_duration_line(line: str) -> float | None:
    _, _, rest = line.partition("Duration:")
    return parse_clock(rest.split(",")[0])


def run_ffmpeg(
    command: list[str], context: ConversionContext, timeout: float
) -> None:
    """Run FFmpeg to completion, reporting progress. Raises on failure/cancel/timeout."""
    try:
        process = popen_command(command)
    except OSError as exc:
        raise ConversionError(f"Could not start FFmpeg: {exc}") from exc

    state: dict = {"total": None, "percent": 0, "tail": deque(maxlen=_TAIL_LINES)}

    def read_output() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            state["tail"].append(line)
            if line.startswith("Duration:"):
                state["total"] = parse_duration_line(line)
            elif line.startswith("out_time="):
                current = parse_clock(line.split("=", 1)[1])
                total = state["total"]
                if current is not None and total:
                    state["percent"] = min(99, int(current / total * 100))

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if context.cancel_event.is_set():
            terminate_process_tree(process)
            raise ConversionCancelled()
        if time.monotonic() > deadline:
            terminate_process_tree(process)
            raise ConversionError("FFmpeg timed out.")
        context.report(state["percent"])
        time.sleep(_POLL_INTERVAL)

    reader.join(timeout=2)

    if process.returncode != 0:
        detail = " | ".join(list(state["tail"])[-4:]) or "no output"
        raise ConversionError(f"FFmpeg failed: {detail}")

    context.report(100)
