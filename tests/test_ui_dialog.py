from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QMessageBox, QToolButton

from app.services.external_tools import ExternalTools
from app.services.settings import OutputMode, Settings
from app.ui.dialogs.convert_dialog import ConvertOptionsDialog
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.theme import LIGHT_COLOR, apply_theme

SCHEMA = {
    "quality": {"type": "int", "min": 1, "max": 100, "default": 90, "label": "Quality"},
    "codec": {"type": "choice", "choices": [("a", "A"), ("b", "B")], "default": "b"},
    "flag": {"type": "bool", "default": True},
    "bg": {"type": "color", "default": "#ffffff"},
    "name": {"type": "string", "default": "x"},
}


def test_dialog_returns_schema_defaults(qtbot):
    dialog = ConvertOptionsDialog(SCHEMA, {})
    assert dialog.values() == {
        "quality": 90,
        "codec": "b",
        "flag": True,
        "bg": "#ffffff",
        "name": "x",
    }


def test_dialog_respects_existing_values(qtbot):
    dialog = ConvertOptionsDialog(SCHEMA, {"quality": 42, "flag": False, "codec": "a"})
    values = dialog.values()
    assert values["quality"] == 42
    assert values["flag"] is False
    assert values["codec"] == "a"


def test_empty_schema_gives_no_values(qtbot):
    dialog = ConvertOptionsDialog({}, {})
    assert dialog.values() == {}


def test_dark_theme_applies_dark_palette(qapp):
    apply_theme(qapp, "dark")
    window = qapp.palette().color(QPalette.ColorRole.Window)
    assert window.lightness() < 128


def test_system_theme_restores_style_palette(qapp):
    apply_theme(qapp, "dark")
    apply_theme(qapp, "system")
    assert qapp.palette().color(
        QPalette.ColorRole.Window
    ) == qapp.style().standardPalette().color(QPalette.ColorRole.Window)


def test_dark_theme_keeps_dark_only_styles(qapp):
    # The menu/disabled-field borders need dark-only rules; leaving dark must drop them
    # while keeping the shared widget styles.
    apply_theme(qapp, "dark")
    assert "QMenu" in qapp.styleSheet()
    apply_theme(qapp, "system")
    assert "QMenu" not in qapp.styleSheet()
    assert "#dropArea" in qapp.styleSheet()  # shared styles stay


def test_light_theme_uses_explicit_light_palette(qapp):
    apply_theme(qapp, "dark")
    assert qapp.palette().color(QPalette.ColorRole.Window).lightness() < 128

    apply_theme(qapp, "light")
    window = qapp.palette().color(QPalette.ColorRole.Window)
    assert window.lightness() > 128
    # Explicit light colours, not whatever the platform style would hand back.
    assert window == QColor(LIGHT_COLOR[QPalette.ColorRole.Window])
    assert qapp.palette().color(QPalette.ColorRole.Base) == QColor(
        LIGHT_COLOR[QPalette.ColorRole.Base]
    )
    assert "QMenu" not in qapp.styleSheet()  # no dark-only rules


def test_settings_theme_applies_immediately_and_reverts_on_cancel(qtbot, qapp):
    apply_theme(qapp, "system")
    settings = Settings(theme="system")
    dialog = SettingsDialog(settings, ExternalTools(settings))
    qtbot.addWidget(dialog)
    assert "QMenu" not in qapp.styleSheet()

    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    assert "QMenu" in qapp.styleSheet()
    assert qapp.palette().color(QPalette.ColorRole.Window).lightness() < 128

    dialog.reject()
    assert "QMenu" not in qapp.styleSheet()


def test_dialog_button_icons_are_cleared(qapp):
    # Adwaita-style themes would otherwise draw palette-independent icons on the
    # OK/Cancel buttons, which vanish on a dark theme. Simulate the style having set
    # them, then a polish pass.
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox

    from app.ui.assets import icon_path
    from app.ui.theme import install_dialog_button_icon_filter

    install_dialog_button_icon_filter(qapp)
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    assert box.buttons()
    for button in box.buttons():
        button.setIcon(QIcon(str(icon_path("question.svg"))))
    assert all(not button.icon().isNull() for button in box.buttons())

    QApplication.sendEvent(box, QEvent(QEvent.Type.Polish))

    assert all(button.icon().isNull() for button in box.buttons())


def test_dark_stylesheet_styles_spinbox_like_line_edit(qapp):
    from app.ui.assets import ICONS_DIR

    apply_theme(qapp, "dark")
    qss = qapp.styleSheet()
    # One selector gives QLineEdit, QSpinBox and QDoubleSpinBox the same border.
    assert "QLineEdit, QSpinBox, QDoubleSpinBox" in qss
    # Spinbox arrows must be supplied, or styling the spinbox drops them.
    assert "arrow-up.svg" in qss and "arrow-down.svg" in qss
    assert (ICONS_DIR / "arrow-up.svg").exists()
    assert (ICONS_DIR / "arrow-down.svg").exists()


def test_path_fields_share_the_same_width(qtbot):
    # Each group box has its own QFormLayout; without equal label columns the tool
    # paths would be a different width from the output folder field.
    settings = Settings()
    dialog = SettingsDialog(settings, ExternalTools(settings))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    widths = {
        dialog.output_directory.width(),
        dialog.ffmpeg_path.width(),
        dialog.libreoffice_path.width(),
    }
    assert widths.pop() > 0
    assert widths == set()


def test_help_buttons_use_the_shared_stylesheet(qtbot, qapp):
    apply_theme(qapp, "light")
    settings = Settings()
    dialog = SettingsDialog(settings, ExternalTools(settings))
    qtbot.addWidget(dialog)
    buttons = dialog.findChildren(QToolButton)
    assert buttons
    assert all(b.objectName() == "helpButton" for b in buttons)
    assert all(not b.styleSheet() for b in buttons)  # style lives in theme.py now
    assert "#helpButton" in qapp.styleSheet()


def test_output_fields_follow_location_mode(qtbot):
    settings = Settings()
    dialog = SettingsDialog(settings, ExternalTools(settings))
    qtbot.addWidget(dialog)

    def select(mode: str) -> None:
        dialog.output_mode.setCurrentIndex(dialog.output_mode.findData(mode))

    # Same folder: neither the custom folder nor the subfolder is used.
    select(OutputMode.SAME_FOLDER.value)
    assert dialog.output_directory_row.isEnabled() is False
    assert dialog.output_subfolder.isEnabled() is False
    assert dialog.output_suffix.isEnabled() is True  # suffix always applies

    # Custom folder: only the folder field applies.
    select(OutputMode.CUSTOM_FOLDER.value)
    assert dialog.output_directory_row.isEnabled() is True
    assert dialog.output_subfolder.isEnabled() is False

    # Subfolder next to source: only the subfolder field applies.
    select(OutputMode.CUSTOM_SUBFOLDER.value)
    assert dialog.output_directory_row.isEnabled() is False
    assert dialog.output_subfolder.isEnabled() is True
    assert dialog.output_suffix.isEnabled() is True


def test_help_icons_explain_settings(qtbot, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *a, **k: calls.append((a[1], a[2]))),
    )
    settings = Settings()
    dialog = SettingsDialog(settings, ExternalTools(settings))
    qtbot.addWidget(dialog)

    buttons = dialog.findChildren(QToolButton)
    assert len(buttons) >= 6

    for button in buttons:
        button.click()

    assert len(calls) == len(buttons)
    assert all(title and body for title, body in calls)
