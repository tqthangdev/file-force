"""Application-wide pointer cursors for interactive controls.

Qt Style Sheets cannot set a cursor, and setting it on every widget by hand is easy to
forget. Instead an application event filter gives buttons, checkboxes, radio buttons and
combo boxes a pointing-hand cursor as they are polished (i.e. created), and clears it
again when they become disabled.

Spin boxes are deliberately excluded: their cursor is finer-grained (hand only over the
stepper buttons) and lives in ``widgets.py``.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractButton, QApplication, QComboBox

_CURSOR_WIDGETS = (QAbstractButton, QComboBox)


class _PointerCursorFilter(QObject):
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if isinstance(obj, _CURSOR_WIDGETS):
            if event.type() in (QEvent.Type.Polish, QEvent.Type.EnabledChange):
                self._apply(obj)
        return False

    @staticmethod
    def _apply(widget) -> None:
        if widget.isEnabled():
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            widget.unsetCursor()


_filter: _PointerCursorFilter | None = None
_app: QApplication | None = None


def install_pointer_cursors(app: QApplication) -> None:
    """Install the filter so every interactive control shows a hand cursor.

    Installing an event filter on the application object makes it receive the events
    sent to every widget in the process. Re-installs if called with a new application.
    """
    global _filter, _app
    if _app is app:
        return
    _filter = _PointerCursorFilter()
    app.installEventFilter(_filter)
    _app = app
