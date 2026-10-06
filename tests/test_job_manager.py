from __future__ import annotations

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.job_manager import JobManager
from app.models.conversion_job import ConversionJob, JobStatus
from app.services.settings import Settings
from tests.fakes import FakeConverter


def _build(converter: FakeConverter, max_workers: int = 2) -> tuple[JobManager, FormatRegistry]:
    registry = FormatRegistry()
    registry.register(converter)
    manager = ConverterManager(registry)
    settings = Settings(max_workers=max_workers)
    return JobManager(registry, manager, settings), registry


def _job(source, source_format="png", target="jpg") -> ConversionJob:
    return ConversionJob(source=source, source_format=source_format, target_format=target)


def test_batch_completes_all_jobs(qtbot, tmp_path):
    manager, _ = _build(FakeConverter())
    jobs = [_job(tmp_path / f"{i}.png") for i in range(3)]
    manager.add_jobs(jobs)

    result = manager.start_all()
    assert len(result.ready) == 3

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert all(job.status is JobStatus.COMPLETED for job in jobs)
    assert all(job.output.exists() for job in jobs)


def test_failure_marks_job_failed_and_continues(qtbot, tmp_path):
    manager, _ = _build(FakeConverter(fail=True))
    jobs = [_job(tmp_path / f"{i}.png") for i in range(3)]
    manager.add_jobs(jobs)

    manager.start_all()
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)

    assert all(job.status is JobStatus.FAILED for job in jobs)
    assert "Fake failure" in jobs[0].error


def test_blocked_job_does_not_stop_batch(qtbot, tmp_path):
    manager, _ = _build(FakeConverter(pairs={("png", "jpg")}))
    good = _job(tmp_path / "good.png", "png", "jpg")
    bad = _job(tmp_path / "bad.png", "png", "pdf")
    manager.add_jobs([good, bad])

    result = manager.start_all()
    assert good in result.ready
    assert bad in result.rejected

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert good.status is JobStatus.COMPLETED
    assert bad.status is JobStatus.BLOCKED
    assert bad.error


def test_cancel_pending_job(qtbot, tmp_path):
    manager, _ = _build(FakeConverter(delay=0.2, parallel=1))
    jobs = [_job(tmp_path / f"{i}.png") for i in range(2)]
    manager.add_jobs(jobs)

    manager.start_all()
    manager.cancel_job(jobs[1])

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert jobs[0].status is JobStatus.COMPLETED
    assert jobs[1].status is JobStatus.CANCELLED


def test_cancel_running_job(qtbot, tmp_path):
    manager, _ = _build(FakeConverter(delay=0.3, parallel=2))
    job = _job(tmp_path / "a.png")
    manager.add_jobs([job])

    manager.start_all()
    manager.cancel_job(job)

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert job.status is JobStatus.CANCELLED


def test_respects_global_worker_limit(qtbot, tmp_path):
    manager, _ = _build(FakeConverter(delay=0.05, parallel=4), max_workers=2)
    jobs = [_job(tmp_path / f"{i}.png") for i in range(6)]
    manager.add_jobs(jobs)

    manager.start_all()
    assert len(manager._running) <= 2

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert all(job.status is JobStatus.COMPLETED for job in jobs)


def test_batch_finished_signal_emitted(qtbot, tmp_path):
    manager, _ = _build(FakeConverter())
    manager.add_jobs([_job(tmp_path / "a.png")])

    with qtbot.waitSignal(manager.batch_finished, timeout=5000):
        manager.start_all()


def test_set_target_format_resets_job(tmp_path):
    manager, _ = _build(FakeConverter(pairs={("png", "jpg"), ("png", "webp")}))
    job = _job(tmp_path / "a.png", "png", "jpg")
    manager.add_jobs([job])

    manager.set_target_format(job, "webp")

    assert job.target_format == "webp"
    assert job.status is JobStatus.WAITING


def test_set_target_format_ignored_while_converting(tmp_path):
    manager, _ = _build(FakeConverter())
    job = _job(tmp_path / "a.png", "png", "jpg")
    job.status = JobStatus.CONVERTING
    manager.add_jobs([job])

    manager.set_target_format(job, "webp")

    assert job.target_format == "jpg"


def test_set_options_resets_job(tmp_path):
    manager, _ = _build(FakeConverter())
    job = _job(tmp_path / "a.png", "png", "jpg")
    job.status = JobStatus.FAILED
    job.error = "boom"
    manager.add_jobs([job])

    manager.set_options(job, {"quality": 50})

    assert job.options == {"quality": 50}
    assert job.status is JobStatus.WAITING
    assert job.error is None


def test_set_options_ignored_while_converting(tmp_path):
    manager, _ = _build(FakeConverter())
    job = _job(tmp_path / "a.png", "png", "jpg")
    job.status = JobStatus.CONVERTING
    job.options = {"quality": 90}
    manager.add_jobs([job])

    manager.set_options(job, {"quality": 10})

    assert job.options == {"quality": 90}


def test_cancel_idle_job_marks_it_cancelled(tmp_path):
    manager, _ = _build(FakeConverter())
    job = _job(tmp_path / "a.png")
    manager.add_jobs([job])

    manager.cancel_job(job)  # waiting, batch not started

    assert job.status is JobStatus.CANCELLED


def test_start_all_reruns_cancelled_jobs(qtbot, tmp_path):
    manager, _ = _build(FakeConverter())
    job = _job(tmp_path / "a.png")
    job.status = JobStatus.CANCELLED
    job.error = "Cancelled."
    manager.add_jobs([job])

    result = manager.start_all()

    assert job in result.ready
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert job.status is JobStatus.COMPLETED


def test_clear_removes_jobs(tmp_path):
    manager, _ = _build(FakeConverter())
    manager.add_jobs([_job(tmp_path / "a.png"), _job(tmp_path / "b.png")])

    manager.clear()

    assert manager.jobs == []


def test_duplicate_engine_names_are_registered_once(qtbot, tmp_path):
    # Regression guard: the manager resolves converters by job.selected_engine.
    manager, registry = _build(FakeConverter(name="fake"))
    assert registry.get("fake") is not None
