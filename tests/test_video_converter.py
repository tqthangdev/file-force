from __future__ import annotations

import threading

import pytest

from app.converters.base import ConversionCancelled, ConversionError
from app.converters.video import VideoConverter
from app.core.format_registry import FormatRegistry
from app.models.conversion_context import ConversionContext
from tests.fakes import FAKE_FFMPEG, SLEEPY_SCRIPT, make_executable


def _make_script(tmp_path, body: str) -> str:
    return make_executable(tmp_path, "fake-ffmpeg", body)


def _context(source, output, **kwargs) -> ConversionContext:
    return ConversionContext(source=source, output=output, **kwargs)


def _mp4(tmp_path, name="clip.mp4"):
    path = tmp_path / name
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return path


# ------------------------------------------------------------------ capability
def test_supported_pairs_cover_video_formats():
    pairs = VideoConverter(resolve_path=lambda: None).supported_pairs()
    assert ("mp4", "webm") in pairs
    assert ("mov", "mkv") in pairs
    assert ("mp4", "mp4") not in pairs


def test_availability_and_reason():
    assert VideoConverter(resolve_path=lambda: None).is_available() is False
    assert VideoConverter(resolve_path=lambda: "/usr/bin/ffmpeg").is_available() is True
    reason = VideoConverter(resolve_path=lambda: None).unavailable_reason() or ""
    assert "FFmpeg" in reason


def test_validate_reports_missing_source(tmp_path):
    converter = VideoConverter(resolve_path=lambda: "/usr/bin/ffmpeg")
    problems = converter.validate("mp4", "webm", tmp_path / "nope.mp4", {})
    assert any("not found" in p for p in problems)


# -------------------------------------------------------------------- execution
def test_convert_writes_output(tmp_path):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    converter = VideoConverter(resolve_path=lambda: script)
    output = tmp_path / "clip.webm"

    result = converter.convert(_context(_mp4(tmp_path), output))

    assert result == output
    assert output.read_bytes() == b"OUT:webm"
    assert not list(tmp_path.glob("*.part"))


def test_progress_reaches_100(tmp_path):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    converter = VideoConverter(resolve_path=lambda: script)
    seen: list[int] = []

    converter.convert(
        _context(_mp4(tmp_path), tmp_path / "clip.mkv", progress_callback=seen.append)
    )

    assert seen and max(seen) == 100


def test_webm_uses_vp9_opus(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(_context(_mp4(tmp_path), tmp_path / "clip.webm"))

    args = record.read_text().splitlines()
    assert args[args.index("-f") + 1] == "webm"
    assert args[args.index("-c:v") + 1] == "libvpx-vp9"
    assert args[args.index("-c:a") + 1] == "libopus"


def test_webm_enables_row_mt_and_speed(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(_context(_mp4(tmp_path), tmp_path / "clip.webm"))

    args = record.read_text().splitlines()
    assert args[args.index("-row-mt") + 1] == "1"
    assert args[args.index("-cpu-used") + 1] == "5"  # balanced default


def test_webm_fast_speed_raises_cpu_used(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(
        _context(_mp4(tmp_path), tmp_path / "clip.webm", options={"speed": "fast"})
    )

    args = record.read_text().splitlines()
    assert args[args.index("-cpu-used") + 1] == "8"


def test_h264_fast_speed_uses_veryfast_preset(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(
        _context(_mp4(tmp_path, "in.mp4"), tmp_path / "out.mp4", options={"speed": "fast"})
    )

    args = record.read_text().splitlines()
    assert args[args.index("-preset") + 1] == "veryfast"


def test_video_runs_one_job_at_a_time():
    assert VideoConverter(resolve_path=lambda: None).max_parallel_jobs() == 1


def test_mp4_uses_h264_faststart(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(_context(_mp4(tmp_path, "in.mp4"), tmp_path / "out.mp4"))

    args = record.read_text().splitlines()
    assert args[args.index("-f") + 1] == "mp4"
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "+faststart" in args


def test_avi_uses_mpeg4_mp3(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(_context(_mp4(tmp_path), tmp_path / "clip.avi"))

    args = record.read_text().splitlines()
    assert args[args.index("-f") + 1] == "avi"
    assert args[args.index("-c:v") + 1] == "mpeg4"
    assert args[args.index("-c:a") + 1] == "libmp3lame"


def test_mkv_uses_matroska_muxer(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = VideoConverter(resolve_path=lambda: script)

    converter.convert(_context(_mp4(tmp_path), tmp_path / "clip.mkv"))

    args = record.read_text().splitlines()
    assert args[args.index("-f") + 1] == "matroska"


def test_timeout_terminates_and_raises(tmp_path):
    script = _make_script(tmp_path, SLEEPY_SCRIPT)
    converter = VideoConverter(resolve_path=lambda: script, timeout=0.4)

    with pytest.raises(ConversionError):
        converter.convert(
            _context(
                _mp4(tmp_path), tmp_path / "clip.mkv", options={"timeout_seconds": 0.4}
            )
        )


def test_cancel_terminates_running_process(tmp_path):
    script = _make_script(tmp_path, SLEEPY_SCRIPT)
    converter = VideoConverter(resolve_path=lambda: script, timeout=30)
    cancel_event = threading.Event()

    with pytest.raises(ConversionCancelled):
        threading.Timer(0.4, cancel_event.set).start()
        converter.convert(
            _context(_mp4(tmp_path), tmp_path / "clip.mkv", cancel_event=cancel_event)
        )


def test_convert_without_tool_raises(tmp_path):
    converter = VideoConverter(resolve_path=lambda: None)
    with pytest.raises(ConversionError):
        converter.convert(_context(_mp4(tmp_path), tmp_path / "clip.mkv"))


# ------------------------------------------------------- registry integration
def test_registry_gates_video_on_ffmpeg():
    registry = FormatRegistry()
    registry.register(VideoConverter(resolve_path=lambda: None))

    assert registry.supports("mp4", "webm") is True
    assert registry.is_available("mp4", "webm") is False
    reason = registry.disabled_reason("mp4", "webm")
    assert reason is not None and "FFmpeg" in reason
    assert "webm" in registry.targets_for("mp4")
