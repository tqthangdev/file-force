from __future__ import annotations

from pathlib import Path

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.preflight import ConflictDecision, Preflight
from app.models.conversion_job import ConversionJob, JobStatus
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
