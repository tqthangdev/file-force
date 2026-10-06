"""QueueModel — a QAbstractListModel over the jobs owned by JobManager.

The model holds no state of its own: it reads ``JobManager.jobs`` and re-emits the
manager's signals as row-level Qt model notifications.
"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt

from app.core.job_manager import JobManager
from app.models.conversion_job import ConversionJob


class JobRoles:
    JOB = Qt.ItemDataRole.UserRole + 1


class QueueModel(QAbstractListModel):
    def __init__(self, manager: JobManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        manager.jobs_added.connect(self._on_jobs_added)
        manager.job_removed.connect(self._on_job_removed)
        manager.job_updated.connect(self._on_job_updated)
        manager.queue_cleared.connect(self._on_cleared)

    # ---------------------------------------------------------------- Qt interface
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.manager.jobs)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job = self.manager.jobs[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return job.filename
        if role == JobRoles.JOB:
            return job
        if role == Qt.ItemDataRole.ToolTipRole:
            return job.error or str(job.source)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def job_at(self, index: QModelIndex) -> ConversionJob | None:
        if not index.isValid():
            return None
        return self.manager.jobs[index.row()]

    # ---------------------------------------------------------------- manager slots
    def _on_jobs_added(self, jobs: list[ConversionJob]) -> None:
        count = len(self.manager.jobs)
        first = count - len(jobs)
        self.beginInsertRows(QModelIndex(), first, count - 1)
        self.endInsertRows()

    def _on_job_removed(self, _job: ConversionJob) -> None:
        self.beginResetModel()
        self.endResetModel()

    def _on_job_updated(self, job: ConversionJob) -> None:
        try:
            row = self.manager.jobs.index(job)
        except ValueError:
            return
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx)

    def _on_cleared(self) -> None:
        self.beginResetModel()
        self.endResetModel()
