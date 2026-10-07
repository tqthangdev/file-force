from __future__ import annotations

from app.services.settings import ImagePdfMode, Settings, max_supported_workers


def test_max_supported_workers_is_at_least_one():
    assert max_supported_workers() >= 1


def test_clamps_caps_workers_to_cpu_count():
    settings = Settings(max_workers=9999)
    settings.clamps()
    assert settings.max_workers == max_supported_workers()


def test_clamps_floor_is_one():
    settings = Settings(max_workers=0)
    settings.clamps()
    assert settings.max_workers == 1


def test_clamps_keeps_a_reasonable_value():
    settings = Settings(max_workers=2)
    settings.clamps()
    assert settings.max_workers == 2


def test_image_pdf_mode_defaults_to_single():
    assert Settings().image_pdf_mode == ImagePdfMode.SINGLE.value


def test_clamps_keeps_a_known_image_pdf_mode():
    settings = Settings(image_pdf_mode=ImagePdfMode.MERGE.value)
    settings.clamps()
    assert settings.image_pdf_mode == ImagePdfMode.MERGE.value


def test_clamps_rejects_an_unknown_image_pdf_mode():
    settings = Settings(image_pdf_mode="whatever")
    settings.clamps()
    assert settings.image_pdf_mode == ImagePdfMode.SINGLE.value
