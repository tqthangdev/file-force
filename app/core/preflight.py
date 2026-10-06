"""Preflight — all output/conflict policy, settled before a job enters the queue.

For each job, in order:

    1. Resolve output path   (output mode, folder, suffix, extension)
    2. Select engine         (ConverterManager; no engine -> BLOCKED with reason)
    3. Validate              (converter.validate(...) -> problems -> BLOCKED)
    4. Resolve conflicts
         a. against existing files on disk  (ask / overwrite / skip / rename)
         b. against other jobs in the same batch

After preflight a job is *ready*: ``output``, ``selected_engine`` and ``options`` are
final. Workers only execute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.models.conversion_job import ConversionJob, JobStatus
from app.services.settings import ConflictMode, Settings
from app.utils.file_utils import build_output_path


class ConflictDecision(Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"


@dataclass
class PreflightResult:
    ready: list[ConversionJob] = field(default_factory=list)
    rejected: list[ConversionJob] = field(default_factory=list)


# ask(job, proposed_path) -> ConflictDecision
AskCallback = Callable[[ConversionJob, Path], ConflictDecision]


class Preflight:
    def __init__(
        self,
        registry: FormatRegistry,
        manager: ConverterManager,
        settings: Settings,
        ask: AskCallback | None = None,
    ) -> None:
        self.registry = registry
        self.manager = manager
        self.settings = settings
        self.ask = ask

    # --------------------------------------------------------------------- batch
    def run(self, jobs: Iterable[ConversionJob]) -> PreflightResult:
        result = PreflightResult()
        reserved: set[Path] = set()
        for job in jobs:
            if job.is_terminal:
                result.rejected.append(job)
                continue
            if self.prepare(job, reserved):
                result.ready.append(job)
            else:
                result.rejected.append(job)
        return result

    # ---------------------------------------------------------------------- one
    def prepare(self, job: ConversionJob, reserved: set[Path] | None = None) -> bool:
        reserved = reserved if reserved is not None else set()

        # 1. Resolve output path
        output_dir = Path(self.settings.output_dir_for(job.source))
        extension = self.registry.primary_extension(job.target_format)
        candidate = build_output_path(
            job.source,
            output_dir,
            extension,
            self.settings.output_suffix,
            avoid_existing=False,
        )

        # 2. Select engine
        converter = self.manager.select_converter(job.source_format, job.target_format)
        if converter is None:
            reason = self.manager.reason_unavailable(job.source_format, job.target_format)
            job.status = JobStatus.BLOCKED
            job.error = reason or "No engine is available for this conversion."
            return False
        job.selected_engine = converter.name

        # 3. Validate
        problems = converter.validate(
            job.source_format, job.target_format, job.source, job.options
        )
        if problems:
            job.status = JobStatus.BLOCKED
            job.error = "; ".join(problems)
            return False

        # 4. Resolve conflicts
        resolved = self._resolve_conflict(job, candidate, reserved)
        if resolved is None:
            job.status = JobStatus.CANCELLED
            job.error = f"Skipped: {candidate.name} already exists."
            return False

        job.output = resolved
        reserved.add(resolved)
        job.status = JobStatus.WAITING
        job.error = None
        return True

    # ------------------------------------------------------------------ conflicts
    def _resolve_conflict(
        self, job: ConversionJob, candidate: Path, reserved: set[Path]
    ) -> Path | None:
        within_batch = candidate in reserved
        if within_batch:
            # Two jobs in one batch must never write the same file: auto-rename.
            return self._unique_in_batch(candidate, reserved)

        if not candidate.exists():
            return candidate

        mode = self.settings.conflict_mode
        if mode == ConflictMode.OVERWRITE.value:
            return candidate
        if mode == ConflictMode.SKIP.value:
            return None
        if mode == ConflictMode.ASK.value and self.ask is not None:
            decision = self.ask(job, candidate)
            if decision is ConflictDecision.OVERWRITE:
                return candidate
            if decision is ConflictDecision.SKIP:
                return None
        # default / RENAME / unanswerable ASK
        return self._unique_in_batch(candidate, reserved)

    @staticmethod
    def _unique_in_batch(candidate: Path, reserved: set[Path]) -> Path:
        stem, suffix, parent = candidate.stem, candidate.suffix, candidate.parent
        index = 1
        while True:
            renamed = parent / f"{stem} ({index}){suffix}"
            if renamed not in reserved and not renamed.exists():
                return renamed
            index += 1
