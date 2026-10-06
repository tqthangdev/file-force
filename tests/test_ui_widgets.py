from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QStyle, QStyleOptionSpinBox

from app.ui.assets import ICONS_DIR, app_icon, icon_path
from app.ui.theme import apply_theme
from app.ui.widgets import DoubleSpinBox, SpinBox


def _up_button_rect(box) -> "object":
    option = QStyleOptionSpinBox()
    box.initStyleOption(option)
    return box.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        option,
        QStyle.SubControl.SC_SpinBoxUp,
        box,
    )


def test_spinbox_shows_hand_cursor_over_buttons(qtbot):
    box = SpinBox()
    box.setRange(1, 10)
    box.resize(140, 34)
    qtbot.addWidget(box)
    box.show()

    QTest.mouseMove(box, _up_button_rect(box).center())
    assert box.cursor().shape() == Qt.CursorShape.PointingHandCursor

    QTest.mouseMove(box, QPoint(5, box.height() // 2))
    assert box.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_double_spinbox_shows_hand_cursor_over_buttons(qtbot):
    box = DoubleSpinBox()
    box.setRange(0.0, 1.0)
    box.resize(140, 34)
    qtbot.addWidget(box)
    box.show()

    QTest.mouseMove(box, _up_button_rect(box).center())
    assert box.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_dark_spinbox_buttons_have_hover_arrows_and_no_separator(qapp):
    apply_theme(qapp, "dark")
    qss = qapp.styleSheet()
    assert "arrow-up-hover.svg" in qss
    assert "arrow-down-hover.svg" in qss
    # The stepper buttons are borderless (no vertical separator line).
    assert "border-left" not in qss


def test_interactive_controls_get_a_hand_cursor(qtbot, qapp):
    from PyQt6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QPushButton,
        QRadioButton,
        QToolButton,
    )

    from app.ui.cursors import install_pointer_cursors

    install_pointer_cursors(qapp)
    widgets = [
        QPushButton("x"),
        QToolButton(),
        QCheckBox("x"),
        QRadioButton("x"),
        QComboBox(),
    ]
    for widget in widgets:
        qtbot.addWidget(widget)
        widget.show()
    qtbot.wait(20)

    assert all(
        widget.cursor().shape() == Qt.CursorShape.PointingHandCursor for widget in widgets
    )


def test_disabled_controls_do_not_get_a_hand_cursor(qtbot, qapp):
    from PyQt6.QtWidgets import QPushButton

    from app.ui.cursors import install_pointer_cursors

    install_pointer_cursors(qapp)
    button = QPushButton("x")
    button.setEnabled(False)
    qtbot.addWidget(button)
    button.show()
    qtbot.wait(20)

    assert button.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_bundled_icons_resolve_and_load(qapp):
    # Regression: after the ui modules moved into subpackages, a wrong relative
    # parents[N] made the icon path point at app/ui/assets and QIcon came back empty.
    from PyQt6.QtGui import QIcon

    from app.ui.dialogs.settings_dialog import _question_icon

    for name in (
        "question.svg",
        "question-hover.svg",
        "arrow-up.svg",
        "arrow-down.svg",
        "arrow-up-hover.svg",
        "arrow-down-hover.svg",
        "add-file.png",
    ):
        path = icon_path(name)
        assert path.exists(), f"missing asset: {path}"
        assert str(path).startswith(str(ICONS_DIR))

    icon = _question_icon()
    assert not icon.isNull()
    assert not icon.pixmap(16, 16).isNull()
    assert not QIcon(str(icon_path("add-file.png"))).isNull()


def test_app_icon_loads_and_is_cached(qapp):
    icon = app_icon()
    assert not icon.isNull()
    for size in (16, 32, 48):
        assert not icon.pixmap(size, size).isNull()
    assert app_icon() is icon  # loaded once
