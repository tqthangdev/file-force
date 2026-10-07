"""ConversionJob — pure data describing one unit of conversion work."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class JobStatus(Enum):
    WAITING = "waiting"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"  # no available engine, or failed preflight


@dataclass
class MergeGroup:
    """Queue rows whose inputs are written into a single output.

    ``jobs`` is in queue order; the first one is the leader that runs the conversion
    and owns the resolved output. Every member points at the same group, so a row can
    reach its group to mirror status, cancel the whole group, or read every input.
    """

    jobs: list["ConversionJob"] = field(default_factory=list)

    @property
    def leader(self) -> "ConversionJob | None":
        return self.jobs[0] if self.jobs else None

    @property
    def sources(self) -> list[Path]:
        return [job.source for job in self.jobs]


@dataclass
class ConversionJob:
    source: Path
    source_format: str
    target_format: str
    output: Path | None = None  # resolved by preflight
    options: dict = field(default_factory=dict)

    selected_engine: str | None = None  # engine NAME, never a converter object
    status: JobStatus = JobStatus.WAITING
    progress: int = 0
    error: str | None = None
    merge: MergeGroup | None = None  # set when this row is part of a merged output

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.BLOCKED,
        )

    @property
    def is_merge_leader(self) -> bool:
        return self.merge is not None and self.merge.leader is self

    @property
    def sources(self) -> list[Path]:
        """Every input this job converts: one, or the whole group when merged."""
        return self.merge.sources if self.merge is not None else [self.source]

    @property
    def filename(self) -> str:
        return self.source.name
