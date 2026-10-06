"""Theme handling and all shared UI styles.

Light and dark are explicit palettes; the system theme uses the style's own palette so
it stays native. Every widget style lives here, keyed by `objectName`, and is applied
as one application stylesheet — so widgets no longer carry their own `setStyleSheet`
strings, and switching themes updates them all at once.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QWidget

from app.ui.assets import ICONS_DIR

THEMES = ["system", "light", "dark"]


class _DialogButtonIconFilter(QObject):
    """Clear the icons a style may draw on standard dialog buttons.

    Some desktop styles (e.g. GNOME/Adwaita) put themed icons on the OK/Cancel buttons
    of a QDialogButtonBox. Those icons do not follow the palette, so on a dark theme
    they blend into the button and become invisible. Clearing them keeps the buttons
    legible on every theme. QMessageBox builds on a QDialogButtonBox too, so its buttons
    are covered as well.

    This is an event filter rather than a QProxyStyle on purpose: calling
    ``QApplication.setStyle`` re-polishes every existing widget and is not safe at
    runtime.
    """

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if isinstance(obj, QDialogButtonBox) and event.type() in (
            QEvent.Type.Polish,
            QEvent.Type.Show,
        ):
            for button in obj.buttons():
                if not button.icon().isNull():
                    button.setIcon(QIcon())
        return False


_icon_filter: _DialogButtonIconFilter | None = None
_icon_filter_app: QApplication | None = None


def install_dialog_button_icon_filter(app: QApplication) -> None:
    """Install the filter (once per application) that strips dialog button icons."""
    global _icon_filter, _icon_filter_app
    if _icon_filter_app is app:
        return
    _icon_filter = _DialogButtonIconFilter()
    app.installEventFilter(_icon_filter)
    _icon_filter_app = app


# Explicit light palette, so choosing "Light" stays light even when the operating
# system is configured for a dark theme.
LIGHT_COLOR = {
    QPalette.ColorRole.Window: "#f0f0f0",
    QPalette.ColorRole.WindowText: "#1a1a1a",
    QPalette.ColorRole.Base: "#ffffff",
    QPalette.ColorRole.AlternateBase: "#f7f7f7",
    QPalette.ColorRole.Text: "#1a1a1a",
    QPalette.ColorRole.Button: "#efefef",
    QPalette.ColorRole.ButtonText: "#1a1a1a",
    QPalette.ColorRole.ToolTipBase: "#ffffdc",
    QPalette.ColorRole.ToolTipText: "#1a1a1a",
    QPalette.ColorRole.Highlight: "#308cc6",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.PlaceholderText: "#909090",
    QPalette.ColorRole.Link: "#0066cc",
    # Frame/separator roles.
    QPalette.ColorRole.Light: "#ffffff",
    QPalette.ColorRole.Midlight: "#e3e3e3",
    QPalette.ColorRole.Mid: "#c0c0c0",
    QPalette.ColorRole.Dark: "#9f9f9f",
    QPalette.ColorRole.Shadow: "#767676",
}

DARK_COLOR = {
    QPalette.ColorRole.Window: "#353535",
    QPalette.ColorRole.WindowText: "#f0f0f0",
    QPalette.ColorRole.Base: "#2b2b2b",
    QPalette.ColorRole.AlternateBase: "#3a3a3a",
    QPalette.ColorRole.Text: "#f0f0f0",
    QPalette.ColorRole.Button: "#353535",
    QPalette.ColorRole.ButtonText: "#f0f0f0",
    QPalette.ColorRole.ToolTipBase: "#2b2b2b",
    QPalette.ColorRole.ToolTipText: "#f0f0f0",
    QPalette.ColorRole.Highlight: "#2a82da",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.PlaceholderText: "#9a9a9a",
    QPalette.ColorRole.Link: "#4da3ff",
    # Frame/separator roles: keep them lighter than the surfaces so borders are visible.
    QPalette.ColorRole.Light: "#5a5a5a",
    QPalette.ColorRole.Midlight: "#565656",
    QPalette.ColorRole.Mid: "#4a4a4a",
    QPalette.ColorRole.Dark: "#2a2a2a",
    QPalette.ColorRole.Shadow: "#1f1f1f",
}

_LIGHT_DISABLED = {
    QPalette.ColorRole.Text: "#9a9a9a",
    QPalette.ColorRole.ButtonText: "#9a9a9a",
    QPalette.ColorRole.WindowText: "#9a9a9a",
}

_DARK_DISABLED = {
    QPalette.ColorRole.Text: "#6f6f6f",
    QPalette.ColorRole.ButtonText: "#6f6f6f",
    QPalette.ColorRole.WindowText: "#6f6f6f",
}

# Secondary colours that are not palette roles but are shared by widgets. Kept here so
# every widget style is defined in one place and follows the theme.
_TOKENS = {
    "light": {
        "muted": "#6b7480",
        "success": "#2e8b57",
        "danger": "#c83232",
        "drop_border": "#9aa4b0",
        "drop_background": "rgba(120, 140, 170, 0.06)",
    },
    "dark": {
        "muted": "#9aa3ae",
        "success": "#7bc99a",
        "danger": "#ef9a9a",
        "drop_border": "#6a7480",
        "drop_background": "rgba(140, 160, 200, 0.12)",
    },
}

# The menu frame and input frames are drawn by the style from shades of the
# background, not from palette roles, so a stylesheet is the only way to make them
# visible on a dark theme. QComboBox is left alone (a stylesheet border would drop its
# native arrow); QSpinBox gets the same border as QLineEdit, with explicit arrow
# images because styling a spinbox otherwise removes its up/down arrows.
_DARK_EXTRAS = f"""
QMenu {{ border: 1px solid #808080; }}
QMenu::separator {{ height: 1px; background: #5a5a5a; margin: 4px 8px; }}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    border: 1px solid #808080; border-radius: 2px; padding: 2px 4px;
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    border: 1px solid #6f6f6f; color: #6f6f6f;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; padding-right: 4px;
    width: 10px; border: none; background: transparent;
    image: url({(ICONS_DIR / 'arrow-up.svg').as_posix()});
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed {{
    image: url({(ICONS_DIR / 'arrow-up-hover.svg').as_posix()});
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; padding-right: 4px;
    width: 10px; border: none; background: transparent;
    image: url({(ICONS_DIR / 'arrow-down.svg').as_posix()});
}}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    image: url({(ICONS_DIR / 'arrow-down-hover.svg').as_posix()});
}}
/* The chevron is drawn by the button itself, so the arrow subcontrol stays empty. */
QSpinBox::up-arrow, QSpinBox::down-arrow,
QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{
    width: 0px; height: 0px;
}}
"""


def _palette(colors: dict, disabled: dict) -> QPalette:
    palette = QPalette()
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role, color in disabled.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return palette


def light_palette() -> QPalette:
    return _palette(LIGHT_COLOR, _LIGHT_DISABLED)


def dark_palette() -> QPalette:
    return _palette(DARK_COLOR, _DARK_DISABLED)


def _resolve_scheme(app: QApplication | None, theme: str) -> str:
    if theme in ("light", "dark"):
        return theme
    if app is not None:
        try:
            if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
                return "dark"
        except (AttributeError, TypeError):
            pass
    return "light"


def stylesheet(theme: str, app: QApplication | None = None) -> str:
    """Build the application stylesheet for a theme name."""
    scheme = _resolve_scheme(app, theme)
    tokens = _TOKENS[scheme]
    qss = f"""
        #dropArea {{
            border: 2px dashed {tokens['drop_border']};
            border-radius: 10px;
            background: {tokens['drop_background']};
        }}
        QLabel#mutedText {{ color: {tokens['muted']}; }}
        QToolButton#helpButton, QPushButton#iconButton {{
            border: none; background: transparent; padding: 0;
        }}
        QToolButton#helpButton:hover, QToolButton#helpButton:pressed,
        QPushButton#iconButton:hover, QPushButton#iconButton:pressed {{
            border: none; background: transparent;
        }}
        QLabel#toolStatus[status="ok"] {{ color: {tokens['success']}; }}
        QLabel#toolStatus[status="error"] {{ color: {tokens['danger']}; }}
    """
    if scheme == "dark":
        qss += _DARK_EXTRAS
    return qss


def color_swatch_qss(color: str) -> str:
    """Style for the colour-picker button (its colour is data-driven)."""
    return f"background-color: {color}; border: 1px solid #888; padding: 4px;"


def set_tool_status(label: QWidget, ok: bool) -> None:
    """Set a status label's `status` property and re-polish so the style applies."""
    label.setProperty("status", "ok" if ok else "error")
    label.style().unpolish(label)
    label.style().polish(label)


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply a theme by name. Unknown values fall back to the system palette."""
    if theme == "dark":
        app.setPalette(dark_palette())
    elif theme == "light":
        app.setPalette(light_palette())
    else:  # "system" — keep the platform's own light/dark palette
        app.setPalette(app.style().standardPalette())
    app.setStyleSheet(stylesheet(theme, app))
