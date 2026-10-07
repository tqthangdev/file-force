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


# Name of the single file a merged job writes (several images -> one PDF). Renames
# add a counter, as with any other conflict.
MERGED_STEM = "merged"


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

        # 1. Resolve output path. A merged job writes a single file for the whole
        #    group, so its name cannot come from one of its sources.
        output_dir = Path(self.settings.output_dir_for(job.source))
        extension = self.registry.primary_extension(job.target_format)
        if job.is_merge_leader:
            candidate = (
                output_dir / f"{MERGED_STEM}{self.settings.output_suffix}.{extension}"
            )
        else:
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
            return self._reject(job, JobStatus.BLOCKED, reason or "No engine is available for this conversion.")
        job.selected_engine = converter.name

        # 3. Validate every input — a merged job has one per page.
        problems: list[str] = []
        for path in job.sources:
            for problem in converter.validate(
                job.source_format, job.target_format, path, job.options
            ):
                if problem not in problems:
                    problems.append(problem)
        if problems:
            return self._reject(job, JobStatus.BLOCKED, "; ".join(problems))

        # 4. Resolve conflicts
        resolved = self._resolve_conflict(job, candidate, reserved)
        if resolved is None:
            return self._reject(
                job, JobStatus.CANCELLED, f"Skipped: {candidate.name} already exists."
            )

        job.output = resolved
        reserved.add(resolved)
        job.status = JobStatus.WAITING
        job.error = None
        self._mirror_to_group(job)
        return True

    def _reject(self, job: ConversionJob, status: JobStatus, message: str) -> bool:
        job.status = status
        job.error = message
        self._mirror_to_group(job)
        return False

    @staticmethod
    def _mirror_to_group(job: ConversionJob) -> None:
        """Give every other row of a merge group the leader's outcome."""
        group = job.merge
        if group is None:
            return
        for member in group.jobs:
            if member is job:
                continue
            member.output = job.output
            member.selected_engine = job.selected_engine
            member.status = job.status
            member.error = job.error
            member.progress = job.progress

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
