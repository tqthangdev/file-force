"""AboutDialog — version (from version.json) and a shortcut to the updater."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
)

from app.core.updater.version import display_version, read_current_version
from app.ui.assets import question_icon
from app.ui.dialogs.version_dialog import VersionDialog


class AboutDialog(QDialog):
    def __init__(
        self,
        parent=None,
        on_update_ready: Optional[Callable[[Path, str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_update_ready = on_update_ready
        self.setWindowTitle("About")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        title = QLabel("FileForge")
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)

        version = QLabel(f"Version {display_version(read_current_version())}")
        version.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        version.setObjectName("mutedText")

        # The "?" next to the version opens the updater dialog.
        help_button = QToolButton()
        help_button.setObjectName("helpButton")
        help_button.setIcon(question_icon())
        help_button.setIconSize(QSize(16, 16))
        help_button.setAutoRaise(True)
        help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        help_button.setToolTip("Check for updates")
        help_button.clicked.connect(self._open_version_dialog)

        version_row = QHBoxLayout()
        version_row.setContentsMargins(0, 0, 0, 0)
        version_row.setSpacing(4)
        version_row.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        version_row.addWidget(help_button, 0, Qt.AlignmentFlag.AlignVCenter)
        version_row.addStretch(1)

        description = QLabel(
            "A desktop file conversion application.\n"
            "Images: Pillow\n"
            "Audio / Video: FFmpeg\n"
            "Documents: LibreOffice"
        )
        description.setAlignment(Qt.AlignmentFlag.AlignLeft)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout.addWidget(title)
        layout.addLayout(version_row)
        layout.addWidget(description)
        layout.addWidget(buttons)

    def _open_version_dialog(self) -> None:
        dialog = VersionDialog(self)
        dialog.exec()
        if dialog.staged_root is not None and self._on_update_ready is not None:
            self._on_update_ready(dialog.staged_root, dialog.staged_version)
            self.accept()
