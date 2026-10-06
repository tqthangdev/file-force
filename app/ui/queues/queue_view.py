"""QueueView — the list widget showing jobs. Pure display plus light interaction."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QListView, QMenu

from app.models.conversion_job import ConversionJob, JobStatus
from app.ui.queues.queue_delegate import QueueDelegate
from app.ui.queues.queue_model import JobRoles, QueueModel


class QueueView(QListView):
    options_requested = pyqtSignal(object)  # ConversionJob
    error_requested = pyqtSignal(object)  # ConversionJob
    cancel_requested = pyqtSignal(object)  # ConversionJob

    def __init__(self, model: QueueModel, delegate: QueueDelegate, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._delegate = delegate
        self.setModel(model)
        self.setItemDelegate(delegate)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    # ------------------------------------------------------------------ keyboard
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._remove_selected()
            return
        super().keyPressEvent(event)

    # --------------------------------------------------------------------- hover
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self.indexAt(event.position().toPoint())
        over_target = False
        if index.isValid():
            rect = self.visualRect(index)
            over_target = self._delegate._target_rect(rect).contains(
                event.position().toPoint()
            )
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if over_target else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            rect = self.visualRect(index)
            if not self._delegate._target_rect(rect).contains(event.position().toPoint()):
                job = index.data(JobRoles.JOB)
                if job is not None:
                    self.options_requested.emit(job)
                    return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------ context
    def _on_context_menu(self, pos: QPoint) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        job: ConversionJob | None = index.data(JobRoles.JOB)

        menu = QMenu(self)
        convert_action = menu.addAction("Convert to…")
        options_action = menu.addAction("Options…")
        menu.addSeparator()
        cancel_action = menu.addAction("Cancel")
        cancel_action.setEnabled(
            job is not None
            and job.status in (JobStatus.WAITING, JobStatus.CONVERTING)
        )
        error_action = menu.addAction("Show error…") if job and job.error else None
        menu.addSeparator()
        remove_action = menu.addAction("Remove")

        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is remove_action:
            for row in sorted(
                {i.row() for i in self.selectionModel().selectedIndexes()}, reverse=True
            ):
                self._model.manager.remove_job(self._model.manager.jobs[row])
        elif chosen is convert_action and job is not None:
            self._delegate._show_target_menu(job, self.viewport().mapToGlobal(pos))
        elif chosen is options_action and job is not None:
            self.options_requested.emit(job)
        elif chosen is cancel_action and job is not None:
            self.cancel_requested.emit(job)
        elif error_action is not None and chosen is error_action and job is not None:
            self.error_requested.emit(job)

    def _remove_selected(self) -> None:
        for row in sorted(
            {i.row() for i in self.selectedIndexes()}, reverse=True
        ):
            self._model.manager.remove_job(self._model.manager.jobs[row])
