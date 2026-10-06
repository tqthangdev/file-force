from __future__ import annotations

import pytest
from PIL import Image

from app.converters.audio import AudioConverter
from app.converters.base import BaseConverter, ConversionError
from app.converters.image import ImageConverter
from app.converters.video import VideoConverter
from app.models.conversion_context import ConversionContext
from tests.fakes import FAKE_FFMPEG, make_executable


class Dummy(BaseConverter):
    pass


def _ctx(source, output, **kwargs) -> ConversionContext:
    return ConversionContext(source=source, output=output, **kwargs)


# --------------------------------------------------------------------- schema
def test_base_converter_has_no_options():
    assert Dummy().options_schema("png", "jpg") == {}


def test_image_options_schema():
    converter = ImageConverter()
    assert "quality" in converter.options_schema("png", "jpg")
    assert "quality" in converter.options_schema("png", "webp")
    assert "quality" not in converter.options_schema("png", "png")
    assert "background" in converter.options_schema("png", "bmp")
    assert "ico_resize" in converter.options_schema("png", "ico")


def test_audio_options_schema():
    converter = AudioConverter(resolve_path=lambda: None)
    assert "bitrate" in converter.options_schema("wav", "mp3")
    assert "compression_level" in converter.options_schema("wav", "flac")
    assert converter.options_schema("wav", "wav") == {}


def test_video_options_schema():
    converter = VideoConverter(resolve_path=lambda: None)
    webm = converter.options_schema("mp4", "webm")
    assert "video_codec" in webm and "quality" in webm and "speed" in webm
    mp4 = converter.options_schema("mkv", "mp4")
    assert "quality" in mp4 and "video_codec" not in mp4 and "speed" in mp4
    avi = converter.options_schema("mp4", "avi")
    assert "quality" not in avi
    assert "resolution" in avi and "remove_audio" in avi


def test_effective_options_merges_provided_over_defaults():
    converter = VideoConverter(resolve_path=lambda: None)
    options = converter.effective_options("mp4", "webm", {"quality": 10})
    assert options["quality"] == 10
    assert options["video_codec"] == "libvpx-vp9"
    assert options["resolution"] == "original"
    assert options["remove_audio"] is False


# --------------------------------------------------------------- image options
def test_image_background_option(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(source)
    output = tmp_path / "a.jpg"

    ImageConverter().convert(
        _ctx(source, output, options={"background": "#000000"})
    )

    with Image.open(output) as image:
        assert all(channel < 30 for channel in image.getpixel((4, 4)))


def test_image_ico_resize_false_raises(tmp_path):
    source = tmp_path / "big.png"
    Image.new("RGB", (512, 512)).save(source)

    with pytest.raises(ConversionError):
        ImageConverter().convert(
            _ctx(source, tmp_path / "big.ico", options={"ico_resize": False})
        )


# --------------------------------------------------------------- audio options
def test_audio_bitrate_option(tmp_path, monkeypatch):
    script = make_executable(tmp_path, "fake-ffmpeg", FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    source = tmp_path / "t.wav"
    source.write_bytes(b"RIFF....WAVE")

    AudioConverter(resolve_path=lambda: script).convert(
        _ctx(source, tmp_path / "t.mp3", options={"bitrate": "320k"})
    )

    args = record.read_text().splitlines()
    assert args[args.index("-b:a") + 1] == "320k"


def test_audio_flac_compression_option(tmp_path, monkeypatch):
    script = make_executable(tmp_path, "fake-ffmpeg", FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    source = tmp_path / "t.wav"
    source.write_bytes(b"RIFF....WAVE")

    AudioConverter(resolve_path=lambda: script).convert(
        _ctx(source, tmp_path / "t.flac", options={"compression_level": 8})
    )

    args = record.read_text().splitlines()
    assert args[args.index("-compression_level") + 1] == "8"


# --------------------------------------------------------------- video options
def test_video_resolution_option(tmp_path, monkeypatch):
    script = make_executable(tmp_path, "fake-ffmpeg", FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    source = tmp_path / "in.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    VideoConverter(resolve_path=lambda: script).convert(
        _ctx(source, tmp_path / "out.mkv", options={"resolution": "480p"})
    )

    args = record.read_text().splitlines()
    assert args[args.index("-vf") + 1] == "scale=-2:480"


def test_video_remove_audio_option(tmp_path, monkeypatch):
    script = make_executable(tmp_path, "fake-ffmpeg", FAKE_FFMPEG)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_FFMPEG_ARGV", str(record))
    source = tmp_path / "in.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    VideoConverter(resolve_path=lambda: script).convert(
        _ctx(source, tmp_path / "out.mp4", options={"remove_audio": True})
    )

    args = record.read_text().splitlines()
    assert "-an" in args
    assert "-c:a" not in args
