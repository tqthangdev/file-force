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

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.BLOCKED,
        )

    @property
    def filename(self) -> str:
        return self.source.name
