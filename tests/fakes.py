"""Fakes and stand-ins shared across tests.

- ``FakeConverter``: a real BaseConverter for queue/preflight tests.
- ``FAKE_FFMPEG`` / ``SLEEPY_SCRIPT``: stand-ins for the ffmpeg binary, so the audio
  and video engines can be tested without ffmpeg installed.
"""
from __future__ import annotations

import time
from pathlib import Path

from app.converters.base import BaseConverter, ConversionCancelled, ConversionError
from app.models.conversion_context import ConversionContext

DEFAULT_PAIRS = {("png", "jpg"), ("png", "webp")}


def make_executable(directory: Path, name: str, body: str) -> str:
    """Write an executable script and return its path as a string."""
    script = directory / name
    script.write_text(body)
    script.chmod(0o755)
    return str(script)


# Emits the -progress stream ffmpeg emits and writes the output file. The output
# content encodes the chosen muxer so tests can assert it.
FAKE_FFMPEG = '''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
record = os.environ.get("FAKE_FFMPEG_ARGV")
if record:
    Path(record).write_text("\\n".join(args))

muxer = None
i = 0
while i < len(args):
    a = args[i]
    if a in ("-i", "-progress", "-b:a", "-c:v", "-c:a", "-crf", "-preset", "-b:v",
             "-q:v", "-pix_fmt", "-movflags", "-vf", "-compression_level",
             "-row-mt", "-cpu-used"):
        i += 2; continue
    if a == "-f":
        muxer = args[i + 1]; i += 2; continue
    i += 1

out = sys.stdout
out.write("Duration: 00:00:10.00, start: 0.0, bitrate: 128 kb/s\\n")
out.write("out_time=00:00:05.000000\\n")
out.write("progress=continue\\n")
out.write("out_time=00:00:10.000000\\n")
out.write("progress=end\\n")
out.flush()

Path(args[-1]).write_bytes(b"OUT:" + (muxer or "?").encode())
'''

SLEEPY_SCRIPT = "#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n"


class FakeConverter(BaseConverter):
    def __init__(
        self,
        name: str = "fake",
        pairs: set[tuple[str, str]] | None = None,
        priority: int = 10,
        available: bool = True,
        reason: str | None = None,
        fail: bool = False,
        delay: float = 0.0,
        parallel: int = 2,
        validate_problems: list[str] | None = None,
        merge_pairs: set[tuple[str, str]] | None = None,
    ) -> None:
        self.name = name
        self.priority = priority
        self._pairs = set(pairs) if pairs is not None else set(DEFAULT_PAIRS)
        self._available = available
        self._reason = reason
        self._fail = fail
        self._delay = delay
        self._parallel = parallel
        self._validate_problems = validate_problems or []
        self._merge_pairs = set(merge_pairs or ())
        self.calls: list[Path] = []
        self.merge_calls: list[list[Path]] = []
        self.validated: list[Path] = []

    def supported_pairs(self) -> set[tuple[str, str]]:
        return set(self._pairs)

    def supports_merge(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self._merge_pairs

    def is_available(self) -> bool:
        return self._available

    def unavailable_reason(self) -> str | None:
        return self._reason

    def max_parallel_jobs(self) -> int:
        return self._parallel

    def validate(self, source_format, target_format, source, options) -> list[str]:
        self.validated.append(source)
        return list(self._validate_problems)

    def convert(self, context: ConversionContext) -> Path:
        self.calls.append(context.source)
        if context.merged:
            self.merge_calls.append(list(context.sources))
        context.report(25)
        if self._delay:
            time.sleep(self._delay)
        if context.cancelled:
            raise ConversionCancelled()
        if self._fail:
            raise ConversionError("Fake failure")
        context.report(75)
        context.output.parent.mkdir(parents=True, exist_ok=True)
        context.output.write_bytes(b"converted")
        context.report(100)
        return context.output
