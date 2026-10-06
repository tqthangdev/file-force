"""AudioConverter — audio conversion and audio extraction via FFmpeg.

Handles audio-to-audio conversion and **video-to-audio extraction** (e.g. ``mp4 -> mp3``):
the video stream is dropped with ``-vn``. FFmpeg is an external tool, invoked as a
subprocess (a list of arguments, never a shell string). Progress, cancellation and
timeout handling live in ``ffmpeg_common.run_ffmpeg``; output is written to a temporary
file and atomically renamed.

All defaults are fixed for v0.3 (lossy targets use 192 kbps); user-facing options
arrive later with ``options_schema()``.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from app.converters.base import BaseConverter, ConversionCancelled, ConversionError
from app.converters.ffmpeg_common import (
    AUDIO_FORMATS,
    VIDEO_FORMATS,
    parse_clock as _parse_clock,
    parse_duration_line as _parse_duration_line,
    run_ffmpeg,
)
from app.models.conversion_context import ConversionContext
from app.utils.file_utils import atomic_output
from app.utils.format_utils import target_from_output

log = logging.getLogger(__name__)

# Sources this engine reads: audio files, plus video files (audio extraction).
AUDIO_SOURCES = AUDIO_FORMATS + VIDEO_FORMATS

# FFmpeg muxer for each target. Needed explicitly because we write to a temp file
# whose extension FFmpeg cannot use to infer the format.
_MUXER = {
    "mp3": "mp3",
    "wav": "wav",
    "flac": "flac",
    "aac": "adts",
    "ogg": "ogg",
    "m4a": "ipod",
}

# Lossy targets get a fixed default bitrate; wav/flac are lossless.
_LOSSY = {"mp3", "aac", "ogg", "m4a"}
_DEFAULT_BITRATE = "192k"

_DEFAULT_TIMEOUT = 1800.0  # files can be long; FFmpeg is fast

__all__ = [
    "AudioConverter",
    "AUDIO_FORMATS",
    "AUDIO_SOURCES",
    "_parse_clock",
    "_parse_duration_line",
]


def default_ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


class AudioConverter(BaseConverter):
    name = "ffmpeg-audio"
    priority = 10

    def __init__(
        self,
        resolve_path: Callable[[], str | None] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._resolve_path = resolve_path or default_ffmpeg_path
        self.timeout = timeout

    # ------------------------------------------------------------------ capability
    def supported_pairs(self) -> set[tuple[str, str]]:
        return {
            (src, dst)
            for src in AUDIO_SOURCES  # audio files and video files (extract audio)
            for dst in AUDIO_FORMATS
            if src != dst
        }

    def is_available(self) -> bool:
        return bool(self._resolve_path())

    def unavailable_reason(self) -> str | None:
        return "Audio conversion needs FFmpeg. Set its path in Settings."

    def max_parallel_jobs(self) -> int:
        return 2

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
        if target_format not in _MUXER:
            problems.append(f"FFmpeg cannot write {target_format.upper()} audio.")
        if not self.is_available():
            problems.append(self.unavailable_reason() or "FFmpeg is not available.")
        return problems

    def options_schema(self, source_format: str, target_format: str) -> dict:
        schema: dict = {}
        if target_format in _LOSSY:
            schema["bitrate"] = {
                "type": "choice",
                "choices": [
                    ("96k", "96 kbps"), ("128k", "128 kbps"), ("192k", "192 kbps"),
                    ("256k", "256 kbps"), ("320k", "320 kbps"),
                ],
                "default": _DEFAULT_BITRATE,
                "label": "Bitrate",
            }
        if target_format == "flac":
            schema["compression_level"] = {
                "type": "int", "min": 0, "max": 8, "default": 5,
                "label": "Compression level",
            }
        return schema

    # ------------------------------------------------------------------- execution
    def convert(self, context: ConversionContext) -> Path:
        executable = self._resolve_path()
        if not executable:
            raise ConversionError(self.unavailable_reason())

        target = target_from_output(context.output)
        muxer = _MUXER.get(target)
        if muxer is None:
            raise ConversionError(f"FFmpeg cannot write {target.upper()} audio.")

        if context.cancelled:
            raise ConversionCancelled()

        options = self.effective_options("", target, context.options)
        timeout = float(context.options.get("timeout_seconds", self.timeout))
        with atomic_output(context.output) as temp_path:
            command = [
                executable,
                "-hide_banner",
                "-nostats",
                "-y",
                "-progress",
                "pipe:1",
                "-i",
                str(context.source),
                "-vn",  # drop any video stream (audio extraction)
                "-f",
                muxer,
                *self._codec_args(target, options),
                str(temp_path),
            ]
            run_ffmpeg(command, context, timeout)
        return context.output

    # -------------------------------------------------------------------- helpers
    def _codec_args(self, target: str, options: dict) -> list[str]:
        if target in _LOSSY:
            return ["-b:a", str(options.get("bitrate", _DEFAULT_BITRATE))]
        if target == "flac":
            level = int(options.get("compression_level", 5))
            return ["-compression_level", str(max(0, min(8, level)))]
        return []
