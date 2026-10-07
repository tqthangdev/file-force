"""JobManager — owns the queue.

Adds and removes jobs, runs preflight before queueing, starts/cancels conversions,
tracks progress and enforces concurrency (the global worker count from settings, and
each engine's ``max_parallel_jobs()``).
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.preflight import AskCallback, Preflight, PreflightResult
from app.core.worker import ConversionWorker
from app.models.conversion_job import ConversionJob, JobStatus, MergeGroup
from app.services.settings import ImagePdfMode, Settings

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
            self._leave_group(job)
            self.jobs.remove(job)
            self.job_removed.emit(job)
            self._maybe_finish_batch()

    def _leave_group(self, job: ConversionJob) -> None:
        """Drop a removed row from its merge group so it is not converted."""
        group = job.merge
        if group is None:
            return
        if job in group.jobs:
            group.jobs.remove(job)
        job.merge = None
        if not group.jobs:
            return
        if len(group.jobs) == 1:
            group.jobs[0].merge = None

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

        # Grouping happens per batch: what the user queued is unchanged, but rows
        # that share an output are converted together by their leader.
        planned = self.plan_batch(candidates)

        for job in candidates:
            job.status = JobStatus.WAITING
            job.progress = 0
            job.error = None
            job.output = None
            job.selected_engine = None

        preflight = Preflight(self.registry, self.manager, self.settings, ask)
        result = preflight.run(planned)
        for job in result.rejected:
            self.job_updated.emit(job)
            self._emit_group_tail(job)
        if not result.ready:
            return result

        for job in result.ready:
            self._emit_group_tail(job)

        self._apply_pool_size()
        self._pending.extend(result.ready)
        self._batch_active = True
        self.batch_started.emit()
        self._pump()
        return result

    def plan_batch(self, candidates: list[ConversionJob]) -> list[ConversionJob]:
        """The jobs to run: mergeable rows collapse into one leader each.

        Rows are grouped by output folder, so images from different folders never end
        up in the same PDF. Merging only happens when it is switched on in settings
        and the engine supports it for the pair.
        """
        if not self._merge_enabled():
            for job in candidates:
                job.merge = None
            return list(candidates)

        buckets: dict[Path, list[ConversionJob]] = {}
        leaders: list[ConversionJob] = []
        for job in candidates:
            job.merge = None
            if not self._can_merge(job):
                leaders.append(job)
                continue
            buckets.setdefault(Path(self.settings.output_dir_for(job.source)), []).append(job)

        for group_jobs in buckets.values():
            if len(group_jobs) < 2:
                leaders.append(group_jobs[0])
                continue
            group = MergeGroup(jobs=list(group_jobs))
            for job in group_jobs:
                job.merge = group
            leaders.append(group_jobs[0])

        order = {id(job): index for index, job in enumerate(candidates)}
        leaders.sort(key=lambda job: order[id(job)])
        return leaders

    def _merge_enabled(self) -> bool:
        return self.settings.image_pdf_mode == ImagePdfMode.MERGE.value

    def _can_merge(self, job: ConversionJob) -> bool:
        converter = self.manager.select_converter(job.source_format, job.target_format)
        return converter is not None and converter.supports_merge(
            job.source_format, job.target_format
        )

    def _emit_group_tail(self, job: ConversionJob) -> None:
        """A group's other rows change whenever their leader does."""
        group = job.merge
        if group is None:
            return
        for member in group.jobs:
            if member is not job:
                self.job_updated.emit(member)

    def _mirror_group(
        self,
        job: ConversionJob,
        *,
        status: JobStatus | None = None,
        progress: int | None = None,
        error: str | None = None,
        output: Path | None = None,
    ) -> None:
        """Apply a group leader's status change to the other rows of its group."""
        group = job.merge
        if group is None:
            return
        for member in group.jobs:
            if member is job:
                continue
            if status is not None:
                member.status = status
            if progress is not None:
                member.progress = progress
            if output is not None:
                member.output = output
            member.error = error
            self.job_updated.emit(member)

    def cancel_job(self, job: ConversionJob) -> None:
        # A merged output cannot be written partially, so cancelling any row of a
        # group cancels the whole group.
        if job.merge is not None and job.merge.leader is not job:
            job = job.merge.leader
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
        self._mirror_group(job, status=JobStatus.CANCELLED, error="Cancelled.")

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
        for key, (stored_job, worker) in list(self._running.items()):
            if stored_job is job:
                del self._running[key]
                break

    def _on_started(self, job: ConversionJob) -> None:
        job.status = JobStatus.CONVERTING
        job.progress = 0
        self.job_updated.emit(job)
        self._mirror_group(job, status=JobStatus.CONVERTING, progress=0, error=None)

    def _on_progress(self, job: ConversionJob, percent: int) -> None:
        job.progress = percent
        self.job_updated.emit(job)
        self._mirror_group(job, progress=percent)

    def _on_finished(self, job: ConversionJob, output: str) -> None:
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.error = None
        self._forget(job)
        self.job_updated.emit(job)
        self._mirror_group(
            job,
            status=JobStatus.COMPLETED,
            progress=100,
            error=None,
            output=Path(output),
        )
        self._after_job()

    def _on_error(self, job: ConversionJob, message: str) -> None:
        job.status = JobStatus.FAILED
        job.error = message
        self._forget(job)
        self.job_updated.emit(job)
        self._mirror_group(job, status=JobStatus.FAILED, error=message)
        self._after_job()

    def _on_cancelled(self, job: ConversionJob) -> None:
        job.status = JobStatus.CANCELLED
        job.error = "Cancelled."
        self._forget(job)
        self.job_updated.emit(job)
        self._mirror_group(job, status=JobStatus.CANCELLED, error="Cancelled.")
        self._after_job()

    def _after_job(self) -> None:
        self._pump()
        self._maybe_finish_batch()

    def _maybe_finish_batch(self) -> None:
        if self._batch_active and not self.is_running():
            self._batch_active = False
            self.batch_finished.emit()
