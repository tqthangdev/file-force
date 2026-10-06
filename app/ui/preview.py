"""PreviewPanel — shows a thumbnail of the selected job's source image.

The thumbnail is decoded on a worker thread (never the GUI thread) and delivered as a
QImage, which is safe to hand across threads.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

from app.core.format_registry import FormatRegistry
from app.models.conversion_job import ConversionJob

THUMBNAIL_SIZE = (220, 220)


class ThumbnailSignals(QObject):
    done = pyqtSignal(object)  # QImage | None


class ThumbnailWorker(QRunnable):
    def __init__(self, path: Path, size: tuple[int, int] = THUMBNAIL_SIZE) -> None:
        super().__init__()
        self.path = path
        self.size = size
        self.signals = ThumbnailSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            with Image.open(self.path) as image:
                image = ImageOps.exif_transpose(image) or image
                image.thumbnail(self.size)
                rgba = image.convert("RGBA")
                data = rgba.tobytes("raw", "RGBA")
                qimage = QImage(
                    data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888
                ).copy()
            self.signals.done.emit(qimage)
        except Exception:  # noqa: BLE001 - a broken preview must never crash the app
            self.signals.done.emit(None)


class PreviewPanel(QGroupBox):
    def __init__(self, registry: FormatRegistry, parent=None) -> None:
        super().__init__("Preview", parent)
        self.registry = registry
        self._workers: set[ThumbnailWorker] = set()

        self._label = QLabel("Select an image to preview")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(240, 240)
        self._label.setWordWrap(True)
        self._label.setObjectName("mutedText")

        layout = QVBoxLayout(self)
        layout.addWidget(self._label, stretch=1)

    def show_job(self, job: ConversionJob | None) -> None:
        self._label.setPixmap(QPixmap())
        if job is None:
            self._label.setText("Select an image to preview")
            return
        if self.registry.category(job.source_format) != "image" or not job.source.exists():
            self._label.setText("No preview for this file type")
            return

        self._label.setText("Loading…")
        worker = ThumbnailWorker(job.source)
        self._workers.add(worker)
        worker.signals.done.connect(lambda image, w=worker: self._on_done(image, w))
        QThreadPool.globalInstance().start(worker)

    def _on_done(self, image, worker: ThumbnailWorker) -> None:
        self._workers.discard(worker)
        if image is None:
            self._label.setText("Preview unavailable")
            return
        self._label.setPixmap(QPixmap.fromImage(image))
