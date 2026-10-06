from __future__ import annotations

import threading

import pytest

from app.converters.audio import (
    AudioConverter,
    _parse_clock,
    _parse_duration_line,
)
from app.converters.base import ConversionCancelled, ConversionError
from app.core.format_registry import FormatRegistry
from app.models.conversion_context import ConversionContext
from tests.fakes import FAKE_FFMPEG, SLEEPY_SCRIPT, make_executable


def _make_script(tmp_path, body: str) -> str:
    return make_executable(tmp_path, "fake-ffmpeg", body)


def _context(source, output, **kwargs) -> ConversionContext:
    return ConversionContext(source=source, output=output, **kwargs)


def _wav(tmp_path, name="tone.wav"):
    path = tmp_path / name
    path.write_bytes(b"RIFF....WAVE")
    return path


# ------------------------------------------------------------------ capability
def test_parse_clock():
    assert _parse_clock("00:00:05.500000") == 5.5
    assert _parse_clock("01:02:03.000000") == 3723.0
    assert _parse_clock("N/A") is None
    assert _parse_clock("") is None


def test_parse_duration_line():
    assert _parse_duration_line("  Duration: 00:00:10.00, start: 0.0") == 10.0
    assert _parse_duration_line("no duration here") is None


def test_supported_pairs_cover_audio_formats():
    pairs = AudioConverter(resolve_path=lambda: None).supported_pairs()
    assert ("wav", "mp3") in pairs
    assert ("mp3", "ogg") in pairs
    assert ("wav", "wav") not in pairs


def test_supported_pairs_include_video_sources():
    pairs = AudioConverter(resolve_path=lambda: None).supported_pairs()
    # Video-to-audio extraction is this engine's job.
    assert ("mp4", "mp3") in pairs
    assert ("mkv", "wav") in pairs
    assert ("webm", "flac") in pairs
    # Video-to-video belongs to the video engine, not here.
    assert ("mp4", "mkv") not in pairs


def test_extraction_drops_the_video_stream(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = AudioConverter(resolve_path=lambda: script)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    converter.convert(_context(source, tmp_path / "clip.mp3"))

    assert "-vn" in record.read_text().splitlines()


def test_video_source_offers_audio_targets():
    registry = FormatRegistry()
    registry.register(AudioConverter(resolve_path=lambda: "/usr/bin/ffmpeg"))
    targets = registry.targets_for("mp4")
    assert "mp3" in targets
    assert "mp4" not in targets  # mp4 is the source format


def test_availability_and_reason():
    assert AudioConverter(resolve_path=lambda: None).is_available() is False
    assert AudioConverter(resolve_path=lambda: "/usr/bin/ffmpeg").is_available() is True
    reason = AudioConverter(resolve_path=lambda: None).unavailable_reason() or ""
    assert "FFmpeg" in reason


def test_max_parallel_jobs_is_bounded():
    assert AudioConverter(resolve_path=lambda: None).max_parallel_jobs() == 2


# ------------------------------------------------------------------ validation
def test_validate_reports_missing_source(tmp_path):
    converter = AudioConverter(resolve_path=lambda: "/usr/bin/ffmpeg")
    problems = converter.validate("wav", "mp3", tmp_path / "nope.wav", {})
    assert any("not found" in p for p in problems)


# -------------------------------------------------------------------- execution
def test_convert_writes_output(tmp_path):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    converter = AudioConverter(resolve_path=lambda: script)
    output = tmp_path / "tone.mp3"

    result = converter.convert(_context(_wav(tmp_path), output))

    assert result == output
    assert output.read_bytes() == b"OUT:mp3"
    assert not list(tmp_path.glob("*.part"))


def test_progress_reaches_100(tmp_path):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    converter = AudioConverter(resolve_path=lambda: script)
    seen: list[int] = []

    converter.convert(
        _context(_wav(tmp_path), tmp_path / "tone.mp3", progress_callback=seen.append)
    )

    assert seen and max(seen) == 100


def test_command_uses_progress_pipe_and_muxer(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = AudioConverter(resolve_path=lambda: script)

    converter.convert(_context(_wav(tmp_path), tmp_path / "tone.mp3"))

    args = record.read_text().splitlines()
    assert "-progress" in args and args[args.index("-progress") + 1] == "pipe:1"
    assert args[args.index("-f") + 1] == "mp3"
    assert "-y" in args


def test_m4a_uses_ipod_muxer(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = AudioConverter(resolve_path=lambda: script)

    converter.convert(_context(_wav(tmp_path), tmp_path / "tone.m4a"))

    args = record.read_text().splitlines()
    assert args[args.index("-f") + 1] == "ipod"


def test_lossy_target_sets_bitrate_flac_does_not(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    converter = AudioConverter(resolve_path=lambda: script)

    converter.convert(_context(_wav(tmp_path), tmp_path / "tone.mp3"))
    assert "-b:a" in record.read_text().splitlines()

    converter.convert(_context(_wav(tmp_path), tmp_path / "tone.flac"))
    assert "-b:a" not in record.read_text().splitlines()


def test_timeout_terminates_and_raises(tmp_path):
    script = _make_script(tmp_path, SLEEPY_SCRIPT)
    converter = AudioConverter(resolve_path=lambda: script, timeout=0.4)

    with pytest.raises(ConversionError):
        converter.convert(
            _context(_wav(tmp_path), tmp_path / "tone.mp3", options={"timeout_seconds": 0.4})
        )


def test_cancel_terminates_running_process(tmp_path):
    script = _make_script(tmp_path, SLEEPY_SCRIPT)
    converter = AudioConverter(resolve_path=lambda: script, timeout=30)
    cancel_event = threading.Event()

    with pytest.raises(ConversionCancelled):
        threading.Timer(0.4, cancel_event.set).start()
        converter.convert(
            _context(_wav(tmp_path), tmp_path / "tone.mp3", cancel_event=cancel_event)
        )


def test_convert_without_tool_raises(tmp_path):
    converter = AudioConverter(resolve_path=lambda: None)
    with pytest.raises(ConversionError):
        converter.convert(_context(_wav(tmp_path), tmp_path / "tone.mp3"))


# ------------------------------------------------------- registry integration
def test_registry_gates_audio_on_ffmpeg():
    registry = FormatRegistry()
    registry.register(AudioConverter(resolve_path=lambda: None))

    assert registry.supports("wav", "mp3") is True
    assert registry.is_available("wav", "mp3") is False
    reason = registry.disabled_reason("wav", "mp3")
    assert reason is not None and "FFmpeg" in reason
    assert "mp3" in registry.targets_for("wav")
