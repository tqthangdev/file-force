from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMessageBox

from app.core.converter_manager import ConverterManager
from app.core.format_registry import FormatRegistry
from app.core.job_manager import JobManager
from app.models.conversion_job import ConversionJob, JobStatus
from app.services.external_tools import ExternalTools
from app.services.settings import Settings
from app.ui.main_window import MainWindow
from tests.fakes import FakeConverter


def _window(
    qtbot, tmp_path, delay: float = 0.0, pairs=None
) -> tuple[MainWindow, JobManager]:
    registry = FormatRegistry()
    registry.register(FakeConverter(delay=delay, pairs=pairs))
    settings = Settings(output_directory=str(tmp_path), output_mode="same_folder")
    tools = ExternalTools(settings)
    manager = JobManager(registry, ConverterManager(registry, tools), settings)
    window = MainWindow(manager, registry, settings, tools)
    qtbot.addWidget(window)
    return window, manager


def _job(tmp_path) -> ConversionJob:
    return ConversionJob(
        source=tmp_path / "a.png", source_format="png", target_format="jpg"
    )


def test_clear_and_convert_shortcuts_follow_buttons(qtbot, tmp_path):
    window, manager = _window(qtbot, tmp_path, delay=0.3)
    manager.add_jobs([_job(tmp_path)])
    window._update_buttons()

    # Idle with jobs: both the buttons and their shortcuts are enabled.
    assert window.clear_button.isEnabled() is True
    assert window.clear_action.isEnabled() is True
    assert window.convert_action.isEnabled() is True

    manager.start_all()
    window._update_buttons()

    # Running: the shortcuts must be disabled just like the buttons, so Ctrl+L can no
    # longer clear (and cancel) the queue.
    assert window.clear_button.isEnabled() is False
    assert window.clear_action.isEnabled() is False
    assert window.convert_action.isEnabled() is False

    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)


def test_quit_action_has_ctrl_q(qtbot, tmp_path):
    window, _ = _window(qtbot, tmp_path)
    quits = [a for a in window.findChildren(QAction) if a.text() == "Quit"]
    assert quits
    assert quits[0].shortcut().toString() == "Ctrl+Q"


def test_convert_all_shortcut(qtbot, tmp_path):
    window, _ = _window(qtbot, tmp_path)
    shortcuts = {s.toString() for s in window.convert_action.shortcuts()}
    assert shortcuts == {"Ctrl+R"}


def test_new_video_jobs_reuse_last_selected_target(qtbot, tmp_path):
    window, manager = _window(
        qtbot, tmp_path, pairs={("mp4", "webm"), ("mp4", "mp3")}
    )
    previous_job = ConversionJob(
        source=tmp_path / "old.mp4", source_format="mp4", target_format="webm"
    )
    manager.add_jobs([previous_job])

    window._set_target_format(previous_job, "mp3")

    assert window._default_target("mp4", ["webm", "mp3"]) == "mp3"


def test_video_jobs_default_to_mp3(qtbot, tmp_path):
    window, _ = _window(
        qtbot, tmp_path, pairs={("mp4", "webm"), ("mp4", "mkv"), ("mp4", "mp3")}
    )

    assert window._default_target("mp4", ["mkv", "mp3", "webm"]) == "mp3"
    assert window._default_target("png", ["jpg", "webp"]) == "jpg"


def test_shortcuts_are_ctrl_based(qtbot, tmp_path):
    # No function keys: the whole scheme is Ctrl-based, plus Delete for list rows.
    window, _ = _window(qtbot, tmp_path)
    for action in window.findChildren(QAction):
        shortcut = action.shortcut().toString()
        if shortcut:
            assert shortcut.startswith("Ctrl+") or shortcut in ("Del",), (
                f"{action.text()!r} uses {shortcut!r}"
            )


def test_window_uses_the_app_icon(qtbot, tmp_path):
    window, _ = _window(qtbot, tmp_path)
    icon = window.windowIcon()
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()


def test_add_files_button_is_icon_only(qtbot, tmp_path):
    window, _ = _window(qtbot, tmp_path)
    button = window.drop_area.add_button
    assert not button.icon().isNull()
    assert button.text() == ""  # icon only
    assert button.toolTip()  # still discoverable


def test_drop_area_shows_hand_cursor(qtbot, tmp_path):
    window, _ = _window(qtbot, tmp_path)
    assert window.drop_area.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_cancel_requested_cancels_job(qtbot, tmp_path):
    window, manager = _window(qtbot, tmp_path)
    job = _job(tmp_path)
    manager.add_jobs([job])

    window.view.cancel_requested.emit(job)

    assert job.status.value == "cancelled"


def test_quit_while_running_can_be_declined(qtbot, tmp_path, monkeypatch):
    window, manager = _window(qtbot, tmp_path, delay=0.4)
    manager.add_jobs([_job(tmp_path)])
    manager.start_all()
    assert manager.is_running()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    assert window.close() is False  # declined -> close ignored
    assert manager.is_running()

    manager.cancel_all()
    manager.wait_for_done(2000)


def test_quit_while_running_confirmed_cancels_jobs(qtbot, tmp_path, monkeypatch):
    window, manager = _window(qtbot, tmp_path, delay=0.4)
    job = _job(tmp_path)
    manager.add_jobs([job])
    manager.start_all()
    assert manager.is_running()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    assert window.close() is True

    # The worker's cancellation is delivered via a queued signal, so let the event
    # loop turn before checking.
    qtbot.waitUntil(lambda: not manager.is_running(), timeout=5000)
    assert job.status is JobStatus.CANCELLED
