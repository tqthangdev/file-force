"""DropArea — accepts files and folders, and offers a browse button.

Folder scanning (especially recursive) runs in a worker so the GUI never blocks.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PyQt6.QtWidgets import QFileDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from app.ui.assets import icon_path


class ScanSignals(QObject):
    done = pyqtSignal(list)  # list[Path]
    failed = pyqtSignal(str)


class FolderScanWorker(QRunnable):
    def __init__(self, folder: Path, recursive: bool) -> None:
        super().__init__()
        self.folder = folder
        self.recursive = recursive
        self.signals = ScanSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            iterator = self.folder.rglob("*") if self.recursive else self.folder.glob("*")
            files = [p for p in iterator if p.is_file()]
        except OSError as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.done.emit(files)


class DropArea(QFrame):
    paths_dropped = pyqtSignal(list)  # list[Path] (files and/or folders)

    def __init__(self, name_filter: str = "", parent=None) -> None:
        super().__init__(parent)
        self.name_filter = name_filter
        self.setAcceptDrops(True)
        self.setMinimumHeight(170)
        self.setObjectName("dropArea")
        # The whole area is clickable (opens the file dialog), so show a hand cursor.
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("DROP FILES HERE")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        title.setFont(font)

        hint = QLabel("or drag folders to import their contents")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("mutedText")

        self.add_button = QPushButton()
        self.add_button.setObjectName("iconButton")
        self.add_button.setToolTip("Add files (Ctrl+O)")
        self.add_button.setAccessibleName("Add files")
        icon_file = icon_path("add-file.png")
        if icon_file.exists():
            self.add_button.setIcon(QIcon(str(icon_file)))
            self.add_button.setIconSize(QSize(80, 80))
        else:
            self.add_button.setText("Add files")  # never leave the button blank
        self.add_button.clicked.connect(self.browse)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignCenter)

    # ---------------------------------------------------------------------- drag
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.paths_dropped.emit(paths)
        event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.browse()
        super().mousePressEvent(event)

    # -------------------------------------------------------------------- browse
    def browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add files", str(Path.home()), self.name_filter
        )
        if files:
            self.paths_dropped.emit([Path(f) for f in files])
