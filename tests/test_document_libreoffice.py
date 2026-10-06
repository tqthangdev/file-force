from __future__ import annotations

import os
import threading

import pytest

from app.converters.base import ConversionCancelled, ConversionError
from app.converters.document_libreoffice import LibreOfficeConverter
from app.core.format_registry import FormatRegistry
from app.models.conversion_context import ConversionContext

# A stand-in for the soffice binary: parses --outdir / --convert-to and writes the
# file LibreOffice would write, so the converter's command building, output discovery
# and atomic move can be tested without LibreOffice installed.
FAKE_SOFFICE = '''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
outdir = None
convert_to = None
source = None
i = 0
while i < len(args):
    a = args[i]
    if a == "--outdir":
        outdir = args[i + 1]; i += 2; continue
    if a == "--convert-to":
        convert_to = args[i + 1]; i += 2; continue
    if a.startswith("-env:") or a.startswith("--"):
        i += 1; continue
    source = a; i += 1

record = os.environ.get("FAKE_SOFFICE_ARGV")
if record:
    Path(record).write_text("\\n".join(args))

ext = convert_to.split(":")[0]
target = Path(outdir) / (Path(source).stem + "." + ext)
target.write_bytes(b"%PDF-1.4\\n%fake pdf\\n" if ext == "pdf" else b"fake output")
'''

SLEEPY_SOFFICE = "#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n"


def _make_script(tmp_path, body: str):
    script = tmp_path / "fake-soffice"
    script.write_text(body)
    script.chmod(0o755)
    return script


def _context(source, output, **kwargs) -> ConversionContext:
    return ConversionContext(source=source, output=output, **kwargs)


def _docx(tmp_path, name="report.docx"):
    path = tmp_path / name
    path.write_bytes(b"PK\x03\x04fake docx")
    return path


# ------------------------------------------------------------------ capability
def test_supported_pairs_include_document_conversions():
    converter = LibreOfficeConverter(resolve_path=lambda: None)
    pairs = converter.supported_pairs()
    assert ("docx", "pdf") in pairs
    assert ("docx", "txt") in pairs
    assert ("odt", "pdf") in pairs
    assert ("txt", "pdf") in pairs
    # No identity pairs, and PDF is a target only (we cannot read PDF).
    assert ("docx", "docx") not in pairs
    assert ("pdf", "docx") not in pairs


def test_is_available_follows_the_resolved_path():
    assert LibreOfficeConverter(resolve_path=lambda: None).is_available() is False
    assert LibreOfficeConverter(resolve_path=lambda: "/usr/bin/soffice").is_available() is True


def test_unavailable_reason_mentions_libreoffice():
    converter = LibreOfficeConverter(resolve_path=lambda: None)
    assert "LibreOffice" in (converter.unavailable_reason() or "")


# ------------------------------------------------------------------ validation
def test_validate_reports_missing_source(tmp_path):
    converter = LibreOfficeConverter(resolve_path=lambda: "/usr/bin/soffice")
    problems = converter.validate("docx", "pdf", tmp_path / "nope.docx", {})
    assert any("not found" in p for p in problems)


def test_validate_reports_missing_tool(tmp_path):
    converter = LibreOfficeConverter(resolve_path=lambda: None)
    problems = converter.validate("docx", "pdf", _docx(tmp_path), {})
    assert any("LibreOffice" in p for p in problems)


# -------------------------------------------------------------------- execution
def test_convert_moves_output_to_resolved_path(tmp_path):
    script = _make_script(tmp_path, FAKE_SOFFICE)
    converter = LibreOfficeConverter(resolve_path=lambda: str(script))
    source = _docx(tmp_path)
    output = tmp_path / "report.pdf"

    result = converter.convert(_context(source, output))

    assert result == output
    assert output.read_bytes().startswith(b"%PDF")
    # The temp conversion directory must be cleaned up.
    assert not list(tmp_path.glob(".fileforge-lo-*"))


def test_convert_builds_expected_arguments(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_SOFFICE)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_SOFFICE_ARGV", str(record))
    converter = LibreOfficeConverter(resolve_path=lambda: str(script))
    source = tmp_path / "notes.txt"
    source.write_text("hello")

    converter.convert(_context(source, tmp_path / "notes.pdf"))

    args = record.read_text().splitlines()
    assert "--headless" in args
    assert args[args.index("--convert-to") + 1] == "pdf"
    assert any(a.startswith("-env:UserInstallation=file://") for a in args)
    assert str(source) in args


def test_txt_target_uses_utf8_filter(tmp_path, monkeypatch):
    script = _make_script(tmp_path, FAKE_SOFFICE)
    record = tmp_path / "argv.txt"
    monkeypatch.setenv("FAKE_SOFFICE_ARGV", str(record))
    converter = LibreOfficeConverter(resolve_path=lambda: str(script))
    source = _docx(tmp_path)

    converter.convert(_context(source, tmp_path / "report.txt"))

    args = record.read_text().splitlines()
    assert args[args.index("--convert-to") + 1] == "txt:Text (encoded):UTF8"
    assert (tmp_path / "report.txt").exists()


def test_timeout_terminates_and_raises(tmp_path):
    script = _make_script(tmp_path, SLEEPY_SOFFICE)
    converter = LibreOfficeConverter(resolve_path=lambda: str(script), timeout=0.4)
    source = _docx(tmp_path)

    with pytest.raises(ConversionError):
        converter.convert(
            _context(source, tmp_path / "report.pdf", options={"timeout_seconds": 0.4})
        )


def test_cancel_terminates_running_process(tmp_path):
    script = _make_script(tmp_path, SLEEPY_SOFFICE)
    converter = LibreOfficeConverter(resolve_path=lambda: str(script), timeout=30)
    source = _docx(tmp_path)
    cancel_event = threading.Event()

    with pytest.raises(ConversionCancelled):
        threading.Timer(0.4, cancel_event.set).start()
        converter.convert(
            _context(source, tmp_path / "report.pdf", cancel_event=cancel_event)
        )


def test_convert_without_tool_raises(tmp_path):
    converter = LibreOfficeConverter(resolve_path=lambda: None)
    with pytest.raises(ConversionError):
        converter.convert(_context(_docx(tmp_path), tmp_path / "out.pdf"))


# ------------------------------------------------------- registry integration
def test_registry_blocks_docx_pdf_when_tool_missing():
    registry = FormatRegistry()
    registry.register(LibreOfficeConverter(resolve_path=lambda: None))

    assert registry.supports("docx", "pdf") is True
    assert registry.is_available("docx", "pdf") is False
    reason = registry.disabled_reason("docx", "pdf")
    assert reason is not None and "LibreOffice" in reason


def test_registry_enables_docx_pdf_when_tool_present(tmp_path):
    registry = FormatRegistry()
    registry.register(LibreOfficeConverter(resolve_path=lambda: "/usr/bin/soffice"))

    assert registry.is_available("docx", "pdf") is True
    assert registry.disabled_reason("docx", "pdf") is None
    assert "pdf" in registry.targets_for("docx")
