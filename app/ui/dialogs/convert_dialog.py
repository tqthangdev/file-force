"""ConvertOptionsDialog — widgets generated from a converter's ``options_schema()``.

The dialog knows nothing about specific formats: it renders whatever spec it is
given. Converters declare their options as data; this is the only place that turns
that data into Qt widgets.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.ui.theme import color_swatch_qss
from app.ui.widgets import DoubleSpinBox, SpinBox


def _prettify(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


class ConvertOptionsDialog(QDialog):
    def __init__(
        self,
        schema: dict,
        values: dict | None = None,
        title: str = "Conversion options",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        values = values or {}
        self._getters: dict = {}

        layout = QVBoxLayout(self)
        if not schema:
            layout.addWidget(QLabel("This conversion has no options."))
        else:
            form = QFormLayout()
            for name, spec in schema.items():
                widget, getter = self._build_widget(spec, values.get(name, spec.get("default")))
                self._getters[name] = getter
                form.addRow(spec.get("label", _prettify(name)), widget)
            layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {name: getter() for name, getter in self._getters.items()}

    # -------------------------------------------------------------------- widgets
    def _build_widget(self, spec: dict, current):
        kind = spec.get("type", "string")
        if kind == "int":
            widget = SpinBox()
            widget.setRange(int(spec.get("min", 0)), int(spec.get("max", 100)))
            widget.setSingleStep(int(spec.get("step", 1)))
            widget.setValue(int(current))
            return widget, widget.value
        if kind == "float":
            widget = DoubleSpinBox()
            widget.setRange(float(spec.get("min", 0.0)), float(spec.get("max", 1.0)))
            widget.setSingleStep(float(spec.get("step", 0.1)))
            widget.setValue(float(current))
            return widget, widget.value
        if kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(current))
            return widget, widget.isChecked
        if kind == "choice":
            widget = QComboBox()
            for value, label in spec.get("choices", []):
                widget.addItem(str(label), value)
            index = widget.findData(current)
            if index >= 0:
                widget.setCurrentIndex(index)
            return widget, widget.currentData
        if kind == "color":
            return self._build_color(spec, current)
        widget = QLineEdit(str(current if current is not None else ""))
        if spec.get("placeholder"):
            widget.setPlaceholderText(spec["placeholder"])
        return widget, widget.text

    def _build_color(self, spec: dict, current):
        state = {"value": str(current or spec.get("default") or "#ffffff")}
        button = QPushButton()

        def refresh() -> None:
            button.setText(state["value"])
            button.setStyleSheet(color_swatch_qss(state["value"]))

        def choose() -> None:
            color = QColorDialog.getColor(QColor(state["value"]), self, "Choose color")
            if color.isValid():
                state["value"] = color.name()
                refresh()

        button.clicked.connect(choose)
        refresh()
        return button, lambda: state["value"]
