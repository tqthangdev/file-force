"""JobManager — owns the queue.

Adds and removes jobs, runs preflight before queueing, starts/cancels conversions,
tracks progress and enforces concurrency (the global worker count from settings, and
each engine's ``max_parallel_jobs()``).
"""
from __future__ import annotations

import logging
from collections import deque

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.preflight import AskCallback, Preflight, PreflightResult
from app.core.worker import ConversionWorker
from app.models.conversion_job import ConversionJob, JobStatus
from app.services.settings import Settings

log = logging.getLogger(__name__)

# Statuses eligible to be (re)queued by start_all. CANCELLED is included so a batch can
# be restarted after cancelling.
_RETRYABLE = (
    JobStatus.WAITING,
    JobStatus.BLOCKED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
)


class JobManager(QObject):
    jobs_added = pyqtSignal(list)  # list[ConversionJob]
    job_removed = pyqtSignal(object)  # ConversionJob
    job_updated = pyqtSignal(object)  # ConversionJob
    queue_cleared = pyqtSignal()
    batch_started = pyqtSignal()
    batch_finished = pyqtSignal()

    def __init__(
        self,
        registry: FormatRegistry,
        manager: ConverterManager,
        settings: Settings,
    ) -> None:
        super().__init__()
        self.registry = registry
        self.manager = manager
        self.settings = settings
        self.jobs: list[ConversionJob] = []

        self._pool = QThreadPool()
        self._pending: deque[ConversionJob] = deque()
        self._running: dict[int, tuple[ConversionJob, ConversionWorker]] = {}
        self._batch_active = False

    # ------------------------------------------------------------------- capacity
    def _apply_pool_size(self) -> None:
        self._pool.setMaxThreadCount(max(1, int(self.settings.max_workers)))

    def _engine_count(self, engine_name: str | None) -> int:
        return sum(1 for job, _w in self._running.values() if job.selected_engine == engine_name)

    def is_running(self) -> bool:
        return bool(self._running) or bool(self._pending)

    # ---------------------------------------------------------------------- queue
    def add_jobs(self, jobs: list[ConversionJob]) -> None:
        if not jobs:
            return
        self.jobs.extend(jobs)
        self.jobs_added.emit(list(jobs))

    def set_target_format(self, job: ConversionJob, target_format: str) -> None:
        """Change a job's target format, resetting it to WAITING."""
        if job.status is JobStatus.CONVERTING or job.target_format == target_format:
            return
        job.target_format = target_format
        job.options.clear()
        job.output = None
        job.selected_engine = None
        job.progress = 0
        job.error = None
        job.status = JobStatus.WAITING
        self.job_updated.emit(job)

    def set_options(self, job: ConversionJob, options: dict) -> None:
        """Replace a job's options, resetting it to WAITING."""
        if job.status is JobStatus.CONVERTING:
            return
        job.options = dict(options)
        job.output = None
        job.selected_engine = None
        job.progress = 0
        job.error = None
        job.status = JobStatus.WAITING
        self.job_updated.emit(job)

    def remove_job(self, job: ConversionJob) -> None:
        if job in self.jobs:
            if job.status is JobStatus.CONVERTING:
                self.cancel_job(job)
            if job in self._pending:
                self._pending.remove(job)
            self.jobs.remove(job)
            self.job_removed.emit(job)
            self._maybe_finish_batch()

    def clear(self) -> None:
        for job in list(self.jobs):
            if job.status is JobStatus.CONVERTING:
                self.cancel_job(job)
        self.jobs = [j for j in self.jobs if j.status is JobStatus.CONVERTING]
        self.queue_cleared.emit()

    # ---------------------------------------------------------------------- batch
    def start_all(self, ask: AskCallback | None = None) -> PreflightResult:
        if self.is_running():
            return PreflightResult()

        candidates = [j for j in self.jobs if j.status in _RETRYABLE]
        if not candidates:
            return PreflightResult()

        for job in candidates:
            job.status = JobStatus.WAITING
            job.progress = 0
            job.error = None
            job.output = None
            job.selected_engine = None

        preflight = Preflight(self.registry, self.manager, self.settings, ask)
        result = preflight.run(candidates)
        for job in result.rejected:
            self.job_updated.emit(job)
        if not result.ready:
            return result

        self._apply_pool_size()
        self._pending.extend(result.ready)
        self._batch_active = True
        self.batch_started.emit()
        self._pump()
        return result

    def cancel_job(self, job: ConversionJob) -> None:
        if job in self._pending:
            self._pending.remove(job)
            self._mark_cancelled(job)
            self._maybe_finish_batch()
            return
        for stored_job, worker in self._running.values():
            if stored_job is job:
                worker.cancel()
                return
        # Not queued and not running (e.g. waiting before Convert All): just mark it,
        # so it will not run and can be restarted later.
        if not job.is_terminal:
            self._mark_cancelled(job)

    def _mark_cancelled(self, job: ConversionJob) -> None:
        job.status = JobStatus.CANCELLED
        job.error = "Cancelled."
        self.job_updated.emit(job)

    def cancel_all(self) -> None:
        for job in list(self._pending):
            self._mark_cancelled(job)
        self._pending.clear()
        for _job, worker in list(self._running.values()):
            worker.cancel()
        self._maybe_finish_batch()

    def wait_for_done(self, timeout_ms: int = -1) -> bool:
        """Block until all submitted workers finish. Intended for tests."""
        return self._pool.waitForDone(timeout_ms)

    # ------------------------------------------------------------------- internal
    def _pump(self) -> None:
        index = 0
        while index < len(self._pending):
            if len(self._running) >= max(1, int(self.settings.max_workers)):
                return
            job = self._pending[index]
            converter = self.registry.get(job.selected_engine or "")
            limit = converter.max_parallel_jobs() if converter else 1
            if self._engine_count(job.selected_engine) >= max(1, limit):
                index += 1  # free capacity may exist for another engine's job
                continue
            self._pending.remove(job)
            self._start(job)

    def _start(self, job: ConversionJob) -> None:
        converter = self.registry.get(job.selected_engine or "")
        if converter is None:
            job.status = JobStatus.FAILED
            job.error = f"Engine {job.selected_engine!r} is not registered."
            self.job_updated.emit(job)
            self._maybe_finish_batch()
            return

        job.status = JobStatus.CONVERTING
        self.job_updated.emit(job)

        worker = ConversionWorker(job, converter)
        worker.signals.started.connect(self._on_started)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        worker.signals.cancelled.connect(self._on_cancelled)
        self._running[id(worker)] = (job, worker)
        self._pool.start(worker)

    def _forget(self, job: ConversionJob) -> None:
        for key, (stored_job, _worker) in list(self._running.items()):
            if stored_job is job:
                del self._running[key]
                break

    def _on_started(self, job: ConversionJob) -> None:
        job.status = JobStatus.CONVERTING
        job.progress = 0
        self.job_updated.emit(job)

    def _on_progress(self, job: ConversionJob, percent: int) -> None:
        job.progress = percent
        self.job_updated.emit(job)

    def _on_finished(self, job: ConversionJob, output: str) -> None:
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.error = None
        self._forget(job)
        self.job_updated.emit(job)
        self._after_job()

    def _on_error(self, job: ConversionJob, message: str) -> None:
        job.status = JobStatus.FAILED
        job.error = message
        self._forget(job)
        self.job_updated.emit(job)
        self._after_job()

    def _on_cancelled(self, job: ConversionJob) -> None:
        job.status = JobStatus.CANCELLED
        job.error = "Cancelled."
        self._forget(job)
        self.job_updated.emit(job)
        self._after_job()

    def _after_job(self) -> None:
        self._pump()
        self._maybe_finish_batch()

    def _maybe_finish_batch(self) -> None:
        if self._batch_active and not self.is_running():
            self._batch_active = False
            self.batch_finished.emit()
