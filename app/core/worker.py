"""ConversionWorker — execute a single ready job on a QThreadPool thread.

The worker builds a ``ConversionContext`` from a ready job (output already resolved
by preflight), calls ``converter.convert(context)`` and reports through Qt signals.
It contains no output-path logic and no conflict policy, and never touches widgets.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.converters.base import BaseConverter, ConversionCancelled, ConversionError
from app.models.conversion_context import ConversionContext
from app.models.conversion_job import ConversionJob

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    started = pyqtSignal(object)  # job
    progress = pyqtSignal(object, int)  # job, percent
    finished = pyqtSignal(object, str)  # job, output path
    error = pyqtSignal(object, str)  # job, message
    cancelled = pyqtSignal(object)  # job


class ConversionWorker(QRunnable):
    def __init__(self, job: ConversionJob, converter: BaseConverter) -> None:
        super().__init__()
        self.job = job
        self.converter = converter
        self.signals = WorkerSignals()
        self.cancel_event = threading.Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        job = self.job
        if self.cancel_event.is_set():
            self.signals.cancelled.emit(job)
            return

        self.signals.started.emit(job)

        output: Path | None = job.output
        if output is None:
            self.signals.error.emit(job, "No output path was resolved.")
            return

        context = ConversionContext(
            source=job.source,
            output=output,
            options=dict(job.options),
            progress_callback=lambda percent: self.signals.progress.emit(job, percent),
            cancel_event=self.cancel_event,
        )

        try:
            result = self.converter.convert(context)
        except ConversionCancelled:
            self.signals.cancelled.emit(job)
            return
        except ConversionError as exc:
            self.signals.error.emit(job, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - isolation: a failure must not kill the pool
            log.exception("Unexpected error converting %s", job.source)
            self.signals.error.emit(job, f"Unexpected error: {exc}")
            return

        if self.cancel_event.is_set():
            self.signals.cancelled.emit(job)
        else:
            self.signals.finished.emit(job, str(result))
