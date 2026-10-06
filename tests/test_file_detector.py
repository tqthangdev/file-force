from __future__ import annotations

import pytest
from PIL import Image

from app.core.file_detector import FileDetector


def _save(path, pil_format, mode="RGB", size=(8, 8)):
    color = (10, 20, 30) if mode == "RGB" else (10, 20, 30, 255)
    Image.new(mode, size, color).save(path, format=pil_format)


def test_detects_png(tmp_path):
    path = tmp_path / "a.png"
    _save(path, "PNG")
    info = FileDetector().detect(path)
    assert info.format == "png"
    assert info.category == "image"
    assert info.extension == ".png"
    assert info.size > 0
    assert info.name == "a.png"


def test_png_renamed_to_jpg_is_detected_as_png(tmp_path):
    path = tmp_path / "tricky.jpg"
    _save(path, "PNG")  # real bytes are PNG, extension claims JPEG
    info = FileDetector().detect(path)
    assert info.format == "png"


def test_detects_jpg_with_jpeg_extension(tmp_path):
    path = tmp_path / "photo.jpeg"
    _save(path, "JPEG")
    info = FileDetector().detect(path)
    assert info.format == "jpg"


def test_detects_webp(tmp_path):
    path = tmp_path / "a.webp"
    _save(path, "WEBP")
    info = FileDetector().detect(path)
    assert info.format == "webp"


def test_unknown_extension_is_other(tmp_path):
    path = tmp_path / "a.zzz"
    path.write_bytes(b"not an image")
    info = FileDetector().detect(path)
    assert info.category == "other"
    assert info.format == "zzz"
