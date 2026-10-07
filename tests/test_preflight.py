from __future__ import annotations

from pathlib import Path

from app.converters.image import ImageConverter
from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.preflight import ConflictDecision, Preflight
from app.models.conversion_job import ConversionJob, JobStatus, MergeGroup
from app.services.settings import ConflictMode, Settings
from tests.fakes import FakeConverter


def _setup(pairs=None, settings=None, ask=None, converter=None):
    registry = FormatRegistry()
    conv = converter or FakeConverter(pairs=pairs or {("png", "jpg")})
    registry.register(conv)
    manager = ConverterManager(registry)
    return Preflight(registry, manager, settings or Settings(), ask), registry


def _job(source: Path, source_format: str, target: str) -> ConversionJob:
    return ConversionJob(source=source, source_format=source_format, target_format=target)


def test_resolves_output_path_in_same_folder(tmp_path):
    preflight, _ = _setup()
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is True
    assert job.output == tmp_path / "a.jpg"
    assert job.selected_engine == "fake"
    assert job.status is JobStatus.WAITING


def test_blocked_when_no_engine(tmp_path):
    preflight, _ = _setup(pairs={("png", "jpg")})
    job = _job(tmp_path / "a.png", "png", "pdf")
    assert preflight.prepare(job) is False
    assert job.status is JobStatus.BLOCKED
    assert job.error


def test_blocked_when_validation_fails(tmp_path):
    converter = FakeConverter(pairs={("png", "jpg")}, validate_problems=["ICO too large"])
    preflight, _ = _setup(converter=converter)
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is False
    assert job.status is JobStatus.BLOCKED
    assert "ICO too large" in job.error


def test_conflict_with_existing_file_renames(tmp_path):
    existing = tmp_path / "a.jpg"
    existing.write_bytes(b"old")
    preflight, _ = _setup(settings=Settings(conflict_mode=ConflictMode.RENAME.value))
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is True
    assert job.output == tmp_path / "a (1).jpg"
    assert existing.read_bytes() == b"old"  # untouched


def test_conflict_within_batch_is_renamed(tmp_path):
    preflight, _ = _setup(pairs={("png", "jpg"), ("jpg", "jpg")})
    first = _job(tmp_path / "a.png", "png", "jpg")
    second = _job(tmp_path / "a.jpg", "jpg", "jpg")
    result = preflight.run([first, second])
    assert len(result.ready) == 2
    assert first.output == tmp_path / "a.jpg"
    assert second.output == tmp_path / "a (1).jpg"


def test_skip_mode_marks_job_cancelled(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"old")
    preflight, _ = _setup(settings=Settings(conflict_mode=ConflictMode.SKIP.value))
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is False
    assert job.status is JobStatus.CANCELLED


def test_overwrite_mode_keeps_path(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"old")
    preflight, _ = _setup(settings=Settings(conflict_mode=ConflictMode.OVERWRITE.value))
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is True
    assert job.output == tmp_path / "a.jpg"


def test_ask_mode_uses_callback(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"old")

    def ask(_job, _path):
        return ConflictDecision.RENAME

    preflight, _ = _setup(settings=Settings(conflict_mode=ConflictMode.ASK.value), ask=ask)
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is True
    assert job.output == tmp_path / "a (1).jpg"


def test_ask_mode_skip_marks_cancelled(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"old")
    preflight, _ = _setup(
        settings=Settings(conflict_mode=ConflictMode.ASK.value),
        ask=lambda *_: ConflictDecision.SKIP,
    )
    job = _job(tmp_path / "a.png", "png", "jpg")
    assert preflight.prepare(job) is False
    assert job.status is JobStatus.CANCELLED


def test_batch_continues_when_one_job_is_blocked(tmp_path):
    registry = FormatRegistry()
    registry.register(FakeConverter(pairs={("png", "jpg")}))
    manager = ConverterManager(registry)
    preflight = Preflight(registry, manager, Settings())
    good = _job(tmp_path / "good.png", "png", "jpg")
    bad = _job(tmp_path / "bad.png", "png", "pdf")
    result = preflight.run([good, bad])
    assert good in result.ready
    assert bad in result.rejected
    assert bad.status is JobStatus.BLOCKED


# ------------------------------------------------------------------ merged jobs
def _merge_setup(tmp_path, converter=None, settings=None):
    registry = FormatRegistry()
    registry.register(
        converter or FakeConverter(pairs={("png", "pdf")}, merge_pairs={("png", "pdf")})
    )
    preflight = Preflight(registry, ConverterManager(registry), settings or Settings())
    jobs = [_job(tmp_path / f"{index}.png", "png", "pdf") for index in range(3)]
    group = MergeGroup(jobs=list(jobs))
    for job in jobs:
        job.merge = group
    return preflight, jobs


def test_merged_job_writes_one_file_for_the_group(tmp_path):
    preflight, jobs = _merge_setup(tmp_path)

    assert preflight.prepare(jobs[0]) is True

    assert jobs[0].output == tmp_path / "merged.pdf"
    assert {job.output for job in jobs} == {tmp_path / "merged.pdf"}
    assert all(job.status is JobStatus.WAITING for job in jobs)
    assert all(job.selected_engine == "fake" for job in jobs)


def test_merged_output_conflict_is_renamed(tmp_path):
    (tmp_path / "merged.pdf").write_bytes(b"old")
    preflight, jobs = _merge_setup(tmp_path)

    assert preflight.prepare(jobs[0]) is True

    assert jobs[0].output == tmp_path / "merged (1).pdf"


def test_merged_job_validates_every_input(tmp_path):
    converter = FakeConverter(pairs={("png", "pdf")}, merge_pairs={("png", "pdf")})
    preflight, jobs = _merge_setup(tmp_path, converter=converter)

    preflight.prepare(jobs[0])

    assert converter.validated == [job.source for job in jobs]


def test_merged_job_is_blocked_when_a_source_is_missing(tmp_path):
    # The real engine checks that every input exists.
    registry = FormatRegistry()
    registry.register(ImageConverter())
    preflight = Preflight(registry, ConverterManager(registry), Settings())
    jobs = [_job(tmp_path / f"{index}.png", "png", "pdf") for index in range(3)]
    for job in jobs:
        job.source.write_bytes(b"not really a png")
    jobs[1].source.unlink()
    group = MergeGroup(jobs=list(jobs))
    for job in jobs:
        job.merge = group

    assert preflight.prepare(jobs[0]) is False

    assert all(job.status is JobStatus.BLOCKED for job in jobs)
    assert "not found" in (jobs[0].error or "")


def test_a_blocked_leader_blocks_every_row_of_the_group(tmp_path):
    converter = FakeConverter(
        pairs={("png", "pdf")},
        merge_pairs={("png", "pdf")},
        validate_problems=["ICO too large"],
    )
    preflight, jobs = _merge_setup(tmp_path, converter=converter)

    assert preflight.prepare(jobs[0]) is False

    assert all(job.status is JobStatus.BLOCKED for job in jobs)
    assert all("ICO too large" in (job.error or "") for job in jobs)
    assert all(job.output is None for job in jobs)
