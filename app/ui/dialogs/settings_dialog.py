"""SettingsDialog — output, conflict, concurrency and external tool paths."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.external_tools import FFMPEG, LIBREOFFICE, ExternalTools
from app.services.settings import (
    ConflictMode,
    OutputMode,
    Settings,
    max_supported_workers,
)
from app.ui.assets import icon_path
from app.ui.theme import apply_theme, set_tool_status
from app.ui.widgets import SpinBox


def _question_icon() -> QIcon:
    """Question-mark icon, using the -hover variant for the active state."""
    icon = QIcon()
    normal = icon_path("question.svg")
    hover = icon_path("question-hover.svg")
    if normal.exists():
        icon.addFile(str(normal), QSize(), QIcon.Mode.Normal, QIcon.State.Off)
    if hover.exists():
        icon.addFile(str(hover), QSize(), QIcon.Mode.Active, QIcon.State.Off)
    return icon


_OUTPUT_MODES = [
    ("Same folder as source", OutputMode.SAME_FOLDER.value),
    ("Custom folder", OutputMode.CUSTOM_FOLDER.value),
    ("Subfolder next to source", OutputMode.CUSTOM_SUBFOLDER.value),
]

_CONFLICT_MODES = [
    ("Rename automatically", ConflictMode.RENAME.value),
    ("Ask each time", ConflictMode.ASK.value),
    ("Overwrite", ConflictMode.OVERWRITE.value),
    ("Skip", ConflictMode.SKIP.value),
]


def _path_row(line_edit: QLineEdit, on_browse) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(line_edit)
    button = QPushButton("Browse…")
    button.clicked.connect(on_browse)
    layout.addWidget(button)
    return widget


class SettingsDialog(QDialog):
    def __init__(
        self, settings: Settings, external_tools: ExternalTools, parent=None
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.external_tools = external_tools
        self._original_theme = settings.theme
        self._help_labels: list[QWidget] = []
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_behavior_group())
        layout.addWidget(self._build_tools_group())
        # Must run after every group exists, so all field columns line up.
        self._equalize_label_widths()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --------------------------------------------------------------------- groups
    def _build_output_group(self) -> QGroupBox:
        box = QGroupBox("Output")
        form = QFormLayout(box)

        self.output_mode = QComboBox()
        for label, value in _OUTPUT_MODES:
            self.output_mode.addItem(label, value)
        self._select_data(self.output_mode, self.settings.output_mode)
        self.output_mode.currentIndexChanged.connect(self._update_output_fields)
        form.addRow(
            self._help_label(
                "Location",
                "Where converted files are written:\n"
                "• Same folder as source — next to the original\n"
                "• Custom folder — one folder you choose\n"
                "• Subfolder next to source — a subfolder beside each source file",
            ),
            self.output_mode,
        )

        self.output_directory = QLineEdit(self.settings.output_directory)
        self.output_directory_row = _path_row(self.output_directory, self._browse_output)
        form.addRow(
            self._help_label(
                "Folder",
                "The destination folder used by the 'Custom folder' location.",
            ),
            self.output_directory_row,
        )

        self.output_subfolder = QLineEdit(self.settings.output_subfolder)
        form.addRow(
            self._help_label(
                "Subfolder name",
                "Name of the folder created next to each source file. Used by the\n"
                "'Subfolder next to source' location.\n"
                "e.g. photo.png → converted/photo.jpg",
            ),
            self.output_subfolder,
        )

        self.output_suffix = QLineEdit(self.settings.output_suffix)
        self.output_suffix.setPlaceholderText("e.g. _converted")
        form.addRow(
            self._help_label(
                "Filename suffix",
                "Text inserted before the file extension in every output name, so\n"
                "results are easy to spot and never overwrite the original.\n"
                "e.g. photo.png → photo_converted.jpg",
            ),
            self.output_suffix,
        )

        self._update_output_fields()
        return box

    def _update_output_fields(self) -> None:
        """Enable only the location fields the selected output mode actually uses."""
        mode = self.output_mode.currentData()
        self.output_directory_row.setEnabled(mode == OutputMode.CUSTOM_FOLDER.value)
        self.output_subfolder.setEnabled(mode == OutputMode.CUSTOM_SUBFOLDER.value)

    def _build_behavior_group(self) -> QGroupBox:
        box = QGroupBox("Behavior")
        form = QFormLayout(box)

        self.conflict_mode = QComboBox()
        for label, value in _CONFLICT_MODES:
            self.conflict_mode.addItem(label, value)
        self._select_data(self.conflict_mode, self.settings.conflict_mode)
        form.addRow(
            self._help_label(
                "On conflict",
                "What to do when the output file already exists:\n"
                "• Rename automatically — add (1), (2), …\n"
                "• Ask each time\n"
                "• Overwrite\n"
                "• Skip",
            ),
            self.conflict_mode,
        )

        self.max_workers = SpinBox()
        self.max_workers.setRange(1, max_supported_workers())
        self.max_workers.setValue(self.settings.max_workers)
        form.addRow(
            self._help_label(
                "Parallel workers",
                "How many conversions run at the same time. Higher finishes large\n"
                f"batches faster but uses more CPU. Default is 2, up to "
                f"{max_supported_workers()} (this machine's CPU count).",
            ),
            self.max_workers,
        )

        self.recursive = QCheckBox("Scan dropped folders recursively")
        self.recursive.setChecked(self.settings.recursive_import)
        form.addRow("", self.recursive)

        self.theme = QComboBox()
        for label, value in (
            ("Follow system", "system"),
            ("Light", "light"),
            ("Dark", "dark"),
        ):
            self.theme.addItem(label, value)
        self._select_data(self.theme, self.settings.theme)
        self.theme.currentIndexChanged.connect(self._preview_theme)
        form.addRow(
            self._help_label(
                "Theme",
                "Colour theme of the app. 'Follow system' matches your OS setting.\n"
                "Changes are applied immediately.",
            ),
            self.theme,
        )
        return box

    def _preview_theme(self, *_args) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.theme.currentData())

    def reject(self) -> None:
        # Undo the live theme preview when the dialog is cancelled.
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._original_theme)
        super().reject()

    def _build_tools_group(self) -> QGroupBox:
        box = QGroupBox("External tools")
        form = QFormLayout(box)

        self.ffmpeg_path = QLineEdit(self.settings.ffmpeg_path)
        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setObjectName("toolStatus")
        form.addRow(
            self._help_label(
                "FFmpeg",
                "External tool used for audio and video conversion. It is detected\n"
                "automatically; set a path here if it is not found.",
            ),
            _path_row(self.ffmpeg_path, lambda: self._browse_tool(self.ffmpeg_path)),
        )
        form.addRow("", self.ffmpeg_status)

        self.libreoffice_path = QLineEdit(self.settings.libreoffice_path)
        self.libreoffice_status = QLabel()
        self.libreoffice_status.setObjectName("toolStatus")
        form.addRow(
            self._help_label(
                "LibreOffice",
                "External tool used for document conversion (doc/docx/odt/rtf/txt\n"
                "→ pdf). It is detected automatically; set a path here if not found.",
            ),
            _path_row(self.libreoffice_path, lambda: self._browse_tool(self.libreoffice_path)),
        )
        form.addRow("", self.libreoffice_status)

        redetect = QPushButton("Re-detect")
        redetect.clicked.connect(self._redetect)
        form.addRow("", redetect)

        self._refresh_tool_status()
        return box

    # ------------------------------------------------------------------- helpers
    def _help_label(self, text: str, explanation: str) -> QWidget:
        """A form label with a question-mark button that explains the setting."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(text)
        label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignVCenter)

        button = QToolButton(container)
        button.setObjectName("helpButton")
        button.setIcon(_question_icon())
        button.setIconSize(QSize(16, 16))
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(f"What does “{text}” do?")
        button.clicked.connect(
            lambda _checked=False, title=text, body=explanation: QMessageBox.information(
                self, title, body
            )
        )
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._help_labels.append(container)
        return container

    def _equalize_label_widths(self) -> None:
        """Give every form label the same width.

        Each group box has its own QFormLayout, so its label column would otherwise be
        sized by its own longest label — leaving the field columns (the text boxes)
        misaligned between groups.
        """
        width = max((w.sizeHint().width() for w in self._help_labels), default=0)
        for widget in self._help_labels:
            widget.setFixedWidth(width)

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _browse_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose output folder", self.output_directory.text() or str(Path.home())
        )
        if chosen:
            self.output_directory.setText(chosen)

    def _browse_tool(self, line_edit: QLineEdit) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "Select executable")
        if chosen:
            line_edit.setText(chosen)
            self._redetect()

    def _refresh_tool_status(self) -> None:
        for key, label in ((FFMPEG, self.ffmpeg_status), (LIBREOFFICE, self.libreoffice_status)):
            info = self.external_tools.get(key)
            if info.available:
                label.setText(f"✓ found: {info.path}")
                set_tool_status(label, True)
            else:
                label.setText("✕ not found")
                set_tool_status(label, False)

    def _redetect(self) -> None:
        self.settings.ffmpeg_path = self.ffmpeg_path.text().strip()
        self.settings.libreoffice_path = self.libreoffice_path.text().strip()
        self.external_tools.detect_all()
        self._refresh_tool_status()

    # -------------------------------------------------------------------- accept
    def _on_accept(self) -> None:
        self.settings.output_mode = self.output_mode.currentData()
        self.settings.output_directory = self.output_directory.text().strip()
        self.settings.output_subfolder = self.output_subfolder.text().strip() or "converted"
        self.settings.output_suffix = self.output_suffix.text().strip()
        self.settings.conflict_mode = self.conflict_mode.currentData()
        self.settings.max_workers = self.max_workers.value()
        self.settings.recursive_import = self.recursive.isChecked()
        self.settings.theme = self.theme.currentData()
        self.settings.ffmpeg_path = self.ffmpeg_path.text().strip()
        self.settings.libreoffice_path = self.libreoffice_path.text().strip()
        self.settings.clamps()
        self.settings.save()
        self.external_tools.detect_all()
        self.accept()
