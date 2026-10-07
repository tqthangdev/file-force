from __future__ import annotations

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.job_manager import JobManager
from app.models.conversion_job import ConversionJob, JobStatus
from app.services.settings import ImagePdfMode, Settings
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
    job.options = {"quality": 50, "remove_audio": True}
    manager.add_jobs([job])

    manager.set_target_format(job, "webp")

    assert job.target_format == "webp"
    assert job.options == {}
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


# ------------------------------------------------------------------- merge mode
def _merge_build(tmp_path, **converter_kwargs):
    converter = FakeConverter(
        pairs={("png", "pdf")}, merge_pairs={("png", "pdf")}, **converter_kwargs
    )
    registry = FormatRegistry()
    registry.register(converter)
    settings = Settings(image_pdf_mode=ImagePdfMode.MERGE.value)
    settings.output_directory = str(tmp_path)
    return JobManager(registry, ConverterManager(registry), settings), converter


def test_merge_mode_writes_one_pdf_for_the_whole_queue(qtbot, tmp_path):
    manager, converter = _merge_build(tmp_path)
    jobs = [_job(tmp_path / f"{i}.png", "png", "pdf") for i in range(3)]
    manager.add_jobs(jobs)

    result = manager.start_all()
    assert result.ready == [jobs[0]]  # one leader runs for the group
    assert jobs[0].is_merge_leader and all(job.merge is jobs[0].merge for job in jobs)

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)

    assert converter.merge_calls == [[job.source for job in jobs]]
    assert converter.calls == [jobs[0].source]  # one conversion, not three
    assert all(job.status is JobStatus.COMPLETED for job in jobs)
    assert len({job.output for job in jobs}) == 1  # every row points at one file
    assert jobs[0].output.exists()


def test_single_mode_keeps_one_output_per_image(qtbot, tmp_path):
    converter = FakeConverter(pairs={("png", "pdf")}, merge_pairs={("png", "pdf")})
    registry = FormatRegistry()
    registry.register(converter)
    manager = JobManager(registry, ConverterManager(registry), Settings())
    jobs = [_job(tmp_path / f"{i}.png", "png", "pdf") for i in range(3)]
    manager.add_jobs(jobs)

    result = manager.start_all()

    assert len(result.ready) == 3
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert converter.merge_calls == []
    assert len({job.output for job in jobs}) == 3


def test_merge_groups_are_per_output_folder(qtbot, tmp_path):
    manager, converter = _merge_build(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    first = [_job(tmp_path / f"{i}.png", "png", "pdf") for i in range(2)]
    second = [_job(nested / f"{i}.png", "png", "pdf") for i in range(2)]
    manager.add_jobs([*first, *second])

    result = manager.start_all()

    assert len(result.ready) == 2  # one leader per folder
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    # The two groups may run in either order.
    merged = sorted(sorted(sources) for sources in converter.merge_calls)
    assert merged == sorted(
        [sorted(job.source for job in first), sorted(job.source for job in second)]
    )


def test_merge_needs_a_pair_the_engine_supports(qtbot, tmp_path):
    converter = FakeConverter(pairs={("png", "jpg")})  # merge_pairs empty
    registry = FormatRegistry()
    registry.register(converter)
    settings = Settings(image_pdf_mode=ImagePdfMode.MERGE.value)
    manager = JobManager(registry, ConverterManager(registry), settings)
    jobs = [_job(tmp_path / f"{i}.png", "png", "jpg") for i in range(3)]
    manager.add_jobs(jobs)

    result = manager.start_all()

    assert len(result.ready) == 3
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert converter.merge_calls == []


def test_a_single_image_in_merge_mode_is_not_merged(qtbot, tmp_path):
    manager, converter = _merge_build(tmp_path)
    job = _job(tmp_path / "only.png", "png", "pdf")
    manager.add_jobs([job])

    manager.start_all()
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)

    assert job.merge is None
    assert job.output == tmp_path / "only.pdf"
    assert converter.merge_calls == []


def test_cancelling_one_row_cancels_the_merged_group(qtbot, tmp_path):
    manager, _ = _merge_build(tmp_path, delay=0.4)
    jobs = [_job(tmp_path / f"{i}.png", "png", "pdf") for i in range(3)]
    manager.add_jobs(jobs)

    manager.start_all()
    manager.cancel_job(jobs[2])  # a follower

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert all(job.status is JobStatus.CANCELLED for job in jobs)


def test_a_failed_merge_fails_every_row(qtbot, tmp_path):
    manager, _ = _merge_build(tmp_path, fail=True)
    jobs = [_job(tmp_path / f"{i}.png", "png", "pdf") for i in range(3)]
    manager.add_jobs(jobs)

    manager.start_all()
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)

    assert all(job.status is JobStatus.FAILED for job in jobs)
    assert all("Fake failure" in (job.error or "") for job in jobs)


def test_removing_a_row_drops_it_from_the_group(tmp_path):
    manager, _ = _merge_build(tmp_path)
    jobs = [_job(tmp_path / f"{i}.png", "png", "pdf") for i in range(3)]
    manager.add_jobs(jobs)
    manager.plan_batch(jobs)

    manager.remove_job(jobs[1])

    assert jobs[1].merge is None
    assert jobs[0].merge.sources == [jobs[0].source, jobs[2].source]
