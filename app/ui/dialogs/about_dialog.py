"""AboutDialog — version and short description."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

VERSION = "0.1.0"


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        title = QLabel("FileForge")
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)

        version = QLabel(f"Version {VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignLeft)
        version.setObjectName("mutedText")

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
        layout.addWidget(version)
        layout.addWidget(description)
        layout.addWidget(buttons)
