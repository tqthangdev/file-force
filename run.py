"""Application entry point.

Creates the QApplication, configures logging, loads settings, detects external tools,
builds the MainWindow and starts the event loop. Contains almost no logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python run.py` from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.core.converter_manager import ConverterManager  # noqa: E402
from app.core.format_registry import FormatRegistry  # noqa: E402
from app.core.job_manager import JobManager  # noqa: E402
from app.converters.audio import AudioConverter  # noqa: E402
from app.converters.document_libreoffice import LibreOfficeConverter  # noqa: E402
from app.converters.image import ImageConverter  # noqa: E402
from app.converters.video import VideoConverter  # noqa: E402
from app.services.external_tools import FFMPEG, LIBREOFFICE, ExternalTools  # noqa: E402
from app.services.logging_setup import setup_logging  # noqa: E402
from app.services.settings import Settings  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.assets import app_icon  # noqa: E402
from app.ui.cursors import install_pointer_cursors  # noqa: E402
from app.ui.theme import apply_theme, install_dialog_button_icon_filter  # noqa: E402


def build_registry(external_tools: ExternalTools) -> FormatRegistry:
    registry = FormatRegistry()
    registry.register(ImageConverter())
    registry.register(
        LibreOfficeConverter(
            resolve_path=lambda: external_tools.get(LIBREOFFICE).path or None
        )
    )
    ffmpeg_path = lambda: external_tools.get(FFMPEG).path or None  # noqa: E731
    registry.register(AudioConverter(resolve_path=ffmpeg_path))
    registry.register(VideoConverter(resolve_path=ffmpeg_path))
    return registry


def main() -> int:
    # The updater process runs the same executable with --update; it must not
    # create a QApplication, it only swaps files and relaunches.
    if "--update" in sys.argv:
        from app.core.updater.apply import run_from_cli

        return run_from_cli(sys.argv[1:])

    setup_logging()
    settings = Settings.load()

    # Clear whatever a finished update left behind (best-effort).
    from app.core.updater.installer import cleanup_staging

    cleanup_staging()

    app = QApplication(sys.argv)
    app.setApplicationName("FileForge")
    app.setOrganizationName("FileForge")
    # Window/taskbar icon for every top-level window (dialogs included).
    app.setWindowIcon(app_icon())
    apply_theme(app, settings.theme)
    install_pointer_cursors(app)
    install_dialog_button_icon_filter(app)

    external_tools = ExternalTools(settings)
    external_tools.detect_all()

    registry = build_registry(external_tools)
    manager = ConverterManager(registry, external_tools)
    job_manager = JobManager(registry, manager, settings)

    window = MainWindow(job_manager, registry, settings, external_tools)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
