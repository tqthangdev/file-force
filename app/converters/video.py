"""VideoConverter — video conversion via FFmpeg.

FFmpeg is an external tool, invoked as a subprocess (a list of arguments, never a
shell string). Progress, cancellation and timeout handling live in
``ffmpeg_common.run_ffmpeg``; output is written to a temporary file and atomically
renamed.

v0.4 uses fixed, broadly compatible codec defaults per container. Resolution / codec /
bitrate options arrive with the options dialog (``options_schema()``, v0.5).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from app.converters.base import BaseConverter, ConversionCancelled, ConversionError
from app.converters.ffmpeg_common import VIDEO_FORMATS, run_ffmpeg
from app.models.conversion_context import ConversionContext
from app.utils.file_utils import atomic_output
from app.utils.format_utils import target_from_output

log = logging.getLogger(__name__)

# FFmpeg muxer for each target. Needed explicitly because we write to a temp file
# whose extension FFmpeg cannot use to infer the format.
_MUXER = {
    "mp4": "mp4",
    "mkv": "matroska",
    "webm": "webm",
    "mov": "mov",
    "avi": "avi",
}

_DEFAULT_TIMEOUT = 3600.0  # long videos can take a while
_H264_CONTAINERS = {"mp4", "mov", "mkv"}
_RESOLUTION_HEIGHTS = {"1080p": 1080, "720p": 720, "480p": 480}

# VP9 is very CPU-heavy: FFmpeg's default cpu-used (~1) makes 1080p encodes take many
# minutes. These presets expose the speed/quality tradeoff; "balanced" is a large
# speedup over the default while keeping quality reasonable. -row-mt 1 is always on.
_USER_SPEED = "balanced"
_VP9_CPU_USED = {"fast": "8", "balanced": "5", "best": "2"}
_X264_PRESET = {"fast": "veryfast", "balanced": "medium", "best": "slow"}


def default_ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _speed_spec() -> dict:
    return {
        "type": "choice",
        "choices": [("fast", "Fast"), ("balanced", "Balanced"), ("best", "Best")],
        "default": _USER_SPEED,
        "label": "Speed",
    }


class VideoConverter(BaseConverter):
    name = "ffmpeg-video"
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
            for src in VIDEO_FORMATS
            for dst in VIDEO_FORMATS
            if src != dst
        }

    def is_available(self) -> bool:
        return bool(self._resolve_path())

    def unavailable_reason(self) -> str | None:
        return "Video conversion needs FFmpeg. Set its path in Settings."

    def max_parallel_jobs(self) -> int:
        # A single FFmpeg encode is already multi-threaded; two at once oversubscribe
        # the CPU and slow everything down.
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
        if target_format not in _MUXER:
            problems.append(f"FFmpeg cannot write {target_format.upper()} video.")
        if not self.is_available():
            problems.append(self.unavailable_reason() or "FFmpeg is not available.")
        return problems

    def options_schema(self, source_format: str, target_format: str) -> dict:
        schema: dict = {}
        if target_format == "webm":
            schema["video_codec"] = {
                "type": "choice",
                "choices": [("libvpx-vp9", "VP9"), ("libvpx", "VP8")],
                "default": "libvpx-vp9",
                "label": "Video codec",
            }
            schema["quality"] = {
                "type": "int", "min": 0, "max": 63, "default": 32,
                "label": "Quality (CRF, lower is better)",
            }
            schema["speed"] = _speed_spec()
        elif target_format in _H264_CONTAINERS:
            schema["quality"] = {
                "type": "int", "min": 0, "max": 51, "default": 23,
                "label": "Quality (CRF, lower is better)",
            }
            schema["speed"] = _speed_spec()
        schema["resolution"] = {
            "type": "choice",
            "choices": [
                ("original", "Original"), ("1080p", "1080p"),
                ("720p", "720p"), ("480p", "480p"),
            ],
            "default": "original",
            "label": "Resolution",
        }
        schema["remove_audio"] = {
            "type": "bool", "default": False, "label": "Remove audio track",
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
            raise ConversionError(f"FFmpeg cannot write {target.upper()} video.")

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
                "-f",
                muxer,
                *self._codec_args(target, options),
                str(temp_path),
            ]
            run_ffmpeg(command, context, timeout)
        return context.output

    # -------------------------------------------------------------------- helpers
    def _codec_args(self, target: str, options: dict) -> list[str]:
        args: list[str] = []
        height = _RESOLUTION_HEIGHTS.get(options.get("resolution"))
        if height:
            args += ["-vf", f"scale=-2:{height}"]  # keep aspect ratio, even width

        remove_audio = bool(options.get("remove_audio", False))
        speed = options.get("speed", _USER_SPEED)

        if target == "webm":
            # WebM only allows VP8/VP9/AV1 video and Vorbis/Opus audio.
            crf = int(options.get("quality", 32))
            cpu_used = _VP9_CPU_USED.get(speed, _VP9_CPU_USED[_USER_SPEED])
            args += [
                "-c:v", str(options.get("video_codec", "libvpx-vp9")),
                "-crf", str(crf), "-b:v", "0",
                "-row-mt", "1", "-cpu-used", cpu_used,
            ]
            if not remove_audio:
                args += ["-c:a", "libopus", "-b:a", "128k"]
        elif target == "avi":
            # Broadly compatible MPEG-4 Part 2 + MP3 for legacy AVI.
            args += ["-c:v", "mpeg4", "-q:v", "4"]
            if not remove_audio:
                args += ["-c:a", "libmp3lame", "-b:a", "192k"]
        elif target in _H264_CONTAINERS:
            crf = int(options.get("quality", 23))
            preset = _X264_PRESET.get(speed, _X264_PRESET[_USER_SPEED])
            args += [
                "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
                "-pix_fmt", "yuv420p",
            ]
            if target in ("mp4", "mov"):
                args += ["-movflags", "+faststart"]
            if not remove_audio:
                args += ["-c:a", "aac", "-b:a", "192k"]

        if remove_audio:
            args.append("-an")
        return args
