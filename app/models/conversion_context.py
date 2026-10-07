"""ConversionContext — the only object a converter receives.

Converters know nothing about job status, engine selection or errors, so they stay
small and easy to test.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class ConversionContext:
    source: Path
    output: Path
    options: dict = field(default_factory=dict)
    progress_callback: Callable[[int], None] = lambda _p: None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # Every input of the job, in order. Only a merged job (a converter that supports
    # it, e.g. several images written into one PDF) has more than one.
    sources: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = [self.source]

    @property
    def merged(self) -> bool:
        return len(self.sources) > 1

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def report(self, percent: int) -> None:
        self.progress_callback(max(0, min(100, int(percent))))
