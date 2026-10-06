"""Small widget subclasses adding behaviour Qt Style Sheets cannot express.

A stylesheet can style a spinbox's subcontrols but cannot set their cursor, and the
spinbox has no child buttons to attach one to. These subclasses therefore watch the
pointer position and show a hand while it is over the up/down buttons.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
)


class _SpinButtonCursorMixin:
    """Show a pointing hand while the pointer is over the spin buttons."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)

    def _over_spin_button(self, pos) -> bool:
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        style = self.style()
        point = pos.toPoint()
        for sub in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown):
            rect = style.subControlRect(
                QStyle.ComplexControl.CC_SpinBox, option, sub, self
            )
            if rect.isValid() and rect.contains(point):
                return True
        return False

    def _update_cursor(self, pos) -> None:
        if self._over_spin_button(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def event(self, event) -> bool:  # noqa: A003
        # HoverMove as well as MouseMove: the internal line edit consumes plain
        # mouse-move events over the text area, but hover still reaches us.
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            self._update_cursor(event.position())
        return super().event(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)


class SpinBox(_SpinButtonCursorMixin, QSpinBox):
    """QSpinBox with a hand cursor over the stepper buttons."""


class DoubleSpinBox(_SpinButtonCursorMixin, QDoubleSpinBox):
    """QDoubleSpinBox with a hand cursor over the stepper buttons."""
