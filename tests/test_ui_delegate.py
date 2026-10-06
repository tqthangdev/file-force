from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QStyleOptionViewItem

from app.ui.queues.queue_delegate import QueueDelegate


def _luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        v = value / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _option(base: str, highlight: str, text: str) -> QStyleOptionViewItem:
    option = QStyleOptionViewItem()
    option.palette.setColor(QPalette.ColorRole.Base, QColor(base))
    option.palette.setColor(QPalette.ColorRole.Highlight, QColor(highlight))
    option.palette.setColor(QPalette.ColorRole.Text, QColor(text))
    return option


def test_selection_background_is_visible_but_not_the_raw_highlight(qtbot):
    option = _option("#ffffff", "#308cc6", "#000000")
    background = QueueDelegate._selection_background(option)
    assert background != QColor("#ffffff")  # selection is visible
    assert background != QColor("#308cc6")  # but not the low-contrast raw highlight


def test_selected_text_stays_high_contrast_light_theme(qtbot):
    option = _option("#ffffff", "#308cc6", "#000000")
    background = QueueDelegate._selection_background(option)
    assert _contrast(background, option.palette.text().color()) >= 7.0
    # The raw highlight would have failed this.
    assert _contrast(QColor("#308cc6"), QColor("#000000")) < 7.0


def test_selected_text_stays_high_contrast_dark_theme(qtbot):
    option = _option("#2b2b2b", "#2a82da", "#f0f0f0")
    background = QueueDelegate._selection_background(option)
    assert _contrast(background, option.palette.text().color()) >= 7.0
