from __future__ import annotations

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from tests.fakes import FakeConverter


def _registry(*converters) -> FormatRegistry:
    registry = FormatRegistry()
    for converter in converters:
        registry.register(converter)
    return registry


def test_selects_highest_priority_available():
    low = FakeConverter(name="low", priority=1, pairs={("png", "jpg")})
    high = FakeConverter(name="high", priority=100, pairs={("png", "jpg")})
    manager = ConverterManager(_registry(low, high))
    assert manager.select("png", "jpg") == "high"


def test_skips_unavailable_engine():
    ghost = FakeConverter(name="ghost", priority=100, pairs={("png", "jpg")}, available=False)
    real = FakeConverter(name="real", priority=1, pairs={("png", "jpg")})
    manager = ConverterManager(_registry(ghost, real))
    assert manager.select("png", "jpg") == "real"


def test_returns_none_when_pair_unsupported():
    manager = ConverterManager(_registry(FakeConverter(name="fake")))
    assert manager.select("png", "pdf") is None


def test_forced_engine_wins():
    low = FakeConverter(name="low", priority=1, pairs={("png", "jpg")})
    high = FakeConverter(name="high", priority=100, pairs={("png", "jpg")})
    manager = ConverterManager(_registry(low, high), forced_engine="low")
    assert manager.select("png", "jpg") == "low"


def test_forced_engine_ignored_when_unavailable():
    ghost = FakeConverter(name="ghost", priority=1, pairs={("png", "jpg")}, available=False)
    real = FakeConverter(name="real", priority=100, pairs={("png", "jpg")})
    manager = ConverterManager(_registry(ghost, real), forced_engine="ghost")
    assert manager.select("png", "jpg") == "real"
