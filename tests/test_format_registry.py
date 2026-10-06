from __future__ import annotations

from app.converters.base import BaseConverter
from app.core.format_registry import FormatRegistry, normalize_format
from tests.fakes import FakeConverter


class PriorityConverter(BaseConverter):
    def __init__(self, name, priority, pairs, available=True):
        self.name = name
        self.priority = priority
        self._pairs = set(pairs)
        self._available = available

    def supported_pairs(self):
        return self._pairs

    def is_available(self):
        return self._available


def test_normalize_format():
    assert normalize_format(".JPEG") == "jpg"
    assert normalize_format("tif") == "tiff"
    assert normalize_format("PNG") == "png"


def test_register_rejects_duplicate_and_empty_names():
    registry = FormatRegistry()
    registry.register(FakeConverter(name="fake"))
    try:
        registry.register(FakeConverter(name="fake"))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate registration should fail")

    try:
        registry.register(FakeConverter(name=""))
    except ValueError:
        pass
    else:
        raise AssertionError("empty name should fail")


def test_targets_for_source():
    registry = FormatRegistry()
    registry.register(FakeConverter(pairs={("png", "jpg"), ("png", "webp"), ("jpg", "png")}))
    assert registry.targets_for("png") == ["jpg", "webp"]
    assert registry.targets_for("jpg") == ["png"]
    assert registry.targets_for("webp") == []


def test_metadata_comes_from_format_info():
    registry = FormatRegistry()
    assert registry.display_name("jpg") == "JPEG"
    assert registry.category("png") == "image"
    assert registry.extensions("tiff") == [".tif", ".tiff"]
    assert registry.primary_extension("jpg") == "jpg"


def test_engines_ordered_by_priority():
    registry = FormatRegistry()
    low = PriorityConverter("low", 1, {("png", "jpg")})
    high = PriorityConverter("high", 100, {("png", "jpg")})
    registry.register(low)
    registry.register(high)
    names = [c.name for c in registry.engines_for("png", "jpg")]
    assert names == ["high", "low"]


def test_availability_and_reason():
    registry = FormatRegistry()
    unavailable = PriorityConverter("ghost", 100, {("png", "jpg")}, available=False)
    available = PriorityConverter("real", 1, {("png", "jpg")}, available=True)
    registry.register(unavailable)
    registry.register(available)

    assert registry.is_available("png", "jpg") is True
    assert registry.available_engines_for("png", "jpg")[0].name == "real"
    assert registry.disabled_reason("png", "jpg") is None


def test_disabled_reason_when_no_engine():
    registry = FormatRegistry()
    reason = registry.disabled_reason("png", "pdf")
    assert reason is not None
    assert "PDF" in reason
