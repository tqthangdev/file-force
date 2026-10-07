from __future__ import annotations

import re
import struct
import threading

import pytest
from PIL import Image

from app.converters.base import ConversionCancelled, ConversionError
from app.converters.image import ImageConverter, target_from_output
from app.models.conversion_context import ConversionContext

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _context(source, output, **kwargs) -> ConversionContext:
    return ConversionContext(source=source, output=output, **kwargs)


def _embedded_ico_png_color_type(path) -> int:
    """Read the PNG color type (byte 25 of IHDR) of the image embedded in an ICO."""
    data = path.read_bytes()
    offset = struct.unpack_from("<I", data, 6 + 12)[0]  # first directory entry
    assert data[offset : offset + 8] == PNG_SIGNATURE, "ICO entry is not a PNG"
    return data[offset + 25]


def test_target_from_output_handles_aliases():
    assert target_from_output(__import__("pathlib").Path("x.tif")) == "tiff"
    assert target_from_output(__import__("pathlib").Path("x.jpeg")) == "jpg"


def test_png_to_jpg(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (16, 16), (200, 10, 10)).save(source)
    output = tmp_path / "a.jpg"

    result = ImageConverter().convert(_context(source, output))

    assert result == output and output.exists()
    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_png_to_webp(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (16, 16), (10, 200, 10)).save(source)
    output = tmp_path / "a.webp"

    ImageConverter().convert(_context(source, output))

    with Image.open(output) as image:
        assert image.format == "WEBP"


def test_jpg_to_png(tmp_path):
    source = tmp_path / "a.jpg"
    Image.new("RGB", (16, 16), (10, 10, 200)).save(source, format="JPEG")
    output = tmp_path / "a.png"

    ImageConverter().convert(_context(source, output))

    with Image.open(output) as image:
        assert image.format == "PNG"


def test_tif_extension_maps_to_tiff(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (16, 16), (1, 1, 1)).save(source)
    output = tmp_path / "a.tif"

    ImageConverter().convert(_context(source, output))

    with Image.open(output) as image:
        assert image.format == "TIFF"


def test_alpha_is_flattened_onto_white_for_jpg(tmp_path):
    source = tmp_path / "alpha.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(source)
    output = tmp_path / "alpha.jpg"

    ImageConverter().convert(_context(source, output))

    with Image.open(output) as image:
        assert image.mode == "RGB"
        assert all(channel > 240 for channel in image.getpixel((4, 4)))


def test_palette_mode_converted_for_png_to_jpg(tmp_path):
    source = tmp_path / "pal.png"
    Image.new("P", (8, 8)).save(source)
    output = tmp_path / "pal.jpg"

    ImageConverter().convert(_context(source, output))

    with Image.open(output) as image:
        assert image.mode == "RGB"


def test_ico_is_resized_to_256(tmp_path):
    source = tmp_path / "big.png"
    Image.new("RGB", (512, 512), (50, 60, 70)).save(source)
    output = tmp_path / "big.ico"

    ImageConverter().convert(_context(source, output))

    with Image.open(output) as image:
        assert max(image.size) <= 256


def test_jpg_to_ico_embeds_rgba_png(tmp_path):
    # Regression: an RGB/palette PNG embedded in ICO breaks GNOME's glycin decoder
    # ("The PNG is not in RGBA format!"). The embedded PNG must be RGBA.
    source = tmp_path / "a.jpg"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(source, format="JPEG")
    output = tmp_path / "a.ico"

    ImageConverter().convert(_context(source, output))

    assert _embedded_ico_png_color_type(output) == 6  # 6 = RGBA


def test_palette_png_to_ico_embeds_rgba_png(tmp_path):
    source = tmp_path / "pal.png"
    Image.new("P", (64, 64)).save(source)
    output = tmp_path / "pal.ico"

    ImageConverter().convert(_context(source, output))

    assert _embedded_ico_png_color_type(output) == 6  # 6 = RGBA


def test_validate_reports_ico_when_resize_disabled(tmp_path):
    source = tmp_path / "big.png"
    Image.new("RGB", (512, 512)).save(source)
    converter = ImageConverter()

    assert converter.validate("png", "ico", source, {}) == []
    assert converter.validate("png", "ico", source, {"ico_resize": False})


def test_unsupported_target_raises(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(source)
    with pytest.raises(ConversionError):
        ImageConverter().convert(_context(source, tmp_path / "a.xyz"))


def test_cancelled_before_start_raises(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(source)
    event = threading.Event()
    event.set()
    with pytest.raises(ConversionCancelled):
        ImageConverter().convert(
            _context(source, tmp_path / "a.jpg", cancel_event=event)
        )


def test_atomic_write_leaves_no_temp_files(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(source)

    ImageConverter().convert(_context(source, tmp_path / "a.jpg"))

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["a.jpg", "a.png"]


def test_convert_reports_progress(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(source)
    seen: list[int] = []

    ImageConverter().convert(
        _context(source, tmp_path / "a.jpg", progress_callback=seen.append)
    )

    assert seen and max(seen) >= 90


def test_exif_orientation_is_applied(tmp_path):
    source = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (10, 20), (1, 2, 3))
    exif = image.getexif()
    exif[274] = 6  # Orientation: rotate 90 degrees
    image.save(source, exif=exif)

    output = tmp_path / "rotated.png"
    ImageConverter().convert(_context(source, output))

    with Image.open(output) as result:
        # A 10x20 image stored with orientation 6 must be corrected to 20x10.
        assert result.size == (20, 10)


# ------------------------------------------------------------------------ PDF
def _pdf_page_count(path) -> int:
    match = re.search(rb"/Count\s+(\d+)", path.read_bytes())
    assert match, "not a PDF page tree"
    return int(match.group(1))


def _pdf_page_sizes(path) -> list[tuple[float, float]]:
    """(width, height) of every page, in points."""
    sizes = []
    for box in re.findall(rb"/MediaBox\s*\[\s*([^\]]+)\]", path.read_bytes()):
        values = [float(v) for v in box.split()]
        sizes.append((values[2] - values[0], values[3] - values[1]))
    return sizes


def test_png_to_pdf_writes_one_page(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (150, 150), (10, 20, 30)).save(source)
    output = tmp_path / "a.pdf"

    result = ImageConverter().convert(_context(source, output))

    assert result == output
    assert output.read_bytes().startswith(b"%PDF-")
    assert _pdf_page_count(output) == 1


def test_png_to_pdf_flattens_transparency(tmp_path):
    # A PDF page cannot store alpha; an RGBA source must still convert.
    source = tmp_path / "alpha.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 0)).save(source)
    output = tmp_path / "alpha.pdf"

    ImageConverter().convert(_context(source, output))

    assert _pdf_page_count(output) == 1


def test_pdf_dpi_option_scales_the_page(tmp_path):
    source = tmp_path / "a.png"
    Image.new("RGB", (150, 150)).save(source)
    output = tmp_path / "a.pdf"

    ImageConverter().convert(_context(source, output, options={"dpi": 300}))

    # 150 px at 300 dpi is half an inch, i.e. 36 points.
    assert _pdf_page_sizes(output) == [(36.0, 36.0)]


def test_merged_images_become_one_pdf_page_each(tmp_path):
    sources = []
    for index, size in enumerate(((200, 100), (100, 300), (150, 150))):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", size, (index * 40, 0, 0)).save(path)
        sources.append(path)
    output = tmp_path / "merged.pdf"

    result = ImageConverter().convert(
        ConversionContext(source=sources[0], output=output, sources=sources)
    )

    assert result == output
    assert _pdf_page_count(output) == 3
    # 150 dpi: 200px -> 96pt, 100px -> 48pt, 150px -> 72pt.
    assert _pdf_page_sizes(output) == [(96.0, 48.0), (48.0, 144.0), (72.0, 72.0)]


def test_merged_context_with_non_pdf_output_raises(tmp_path):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    for path in (first, second):
        Image.new("RGB", (8, 8)).save(path)

    with pytest.raises(ConversionError):
        ImageConverter().convert(
            ConversionContext(
                source=first, output=tmp_path / "merged.jpg", sources=[first, second]
            )
        )


def test_merge_is_only_offered_for_pdf():
    converter = ImageConverter()
    assert converter.supports_merge("png", "pdf") is True
    assert converter.supports_merge("jpg", "pdf") is True
    assert converter.supports_merge("png", "jpg") is False
    assert converter.supports_merge("pdf", "png") is False


def test_pdf_is_offered_as_a_target():
    pairs = ImageConverter().supported_pairs()
    assert ("png", "pdf") in pairs
    assert ("jpg", "pdf") in pairs

