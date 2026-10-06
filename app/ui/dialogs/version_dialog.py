"""Version dialog: shows the running version, checks GitHub Releases for a newer
build and, on request, downloads and stages it.

Checking and downloading run on worker threads (with Qt signals carrying the
result back), so the modal dialog stays responsive.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLayout,
    QProgressBar,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
)

from app.core.updater.checker import UpdateError, check_for_update
from app.core.updater.installer import InstallError, prepare_update
from app.core.updater.paths import is_frozen
from app.core.updater.version import display_version, read_current_version
from app.ui.cursors import install_pointer_cursors

NOTES_ARROW_DOWN = "\u25bc"  # ▼ collapsed
NOTES_ARROW_UP = "\u25b2"    # ▲ expanded

# GitHub appends this comparison link to auto-generated release notes; it is
# noise in the dialog, so it is dropped before the notes are shown.
_FULL_CHANGELOG_RE = re.compile(
    r"^\s*\*{0,2}\s*Full Changelog\s*\*{0,2}\s*:.*$", re.IGNORECASE | re.MULTILINE
)


def clean_notes(text: str) -> str:
    """Strip the boilerplate GitHub adds to auto-generated release notes."""
    cleaned = _FULL_CHANGELOG_RE.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# Buttons shown in each dialog state.
STATE_BUTTONS = {
    "checking": ("close",),
    "available": ("update", "later"),
    "uptodate": ("close",),
    "error": ("retry", "close"),
    "downloading": ("cancel",),
    "ready": (),
}


class VersionDialog(QDialog):
    """Modal that reports the version and can stage an update."""

    _checked = pyqtSignal(object)      # ("ok", UpdateInfo) | ("error", message)
    _progress = pyqtSignal(int, int)   # (bytes_done, bytes_total)
    _staged = pyqtSignal(str)          # staged app root
    _stage_failed = pyqtSignal(str)    # error message or stable code

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Version")
        self.setModal(True)
        self.setMinimumWidth(440)

        # Set once an update is prepared; read by the caller to start the swap.
        self.staged_root: Path | None = None
        self.staged_version = ""

        self._info = None
        self._cancel = threading.Event()
        self._closed = False

        layout = QVBoxLayout(self)
        # Grow (never shrink below) whatever the content needs, otherwise a
        # message that appears after the dialog is shown gets squeezed.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.title_label = QLabel("Version")
        font = self.title_label.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label)

        self.current_label = QLabel("")
        layout.addWidget(self.current_label)

        self.latest_label = QLabel("")
        self.latest_label.setVisible(False)
        layout.addWidget(self.latest_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        # Release notes: a collapse/expand header with the full text below.
        self._notes = ""
        self._notes_expanded = False
        self.notes_toggle = QToolButton()
        self.notes_toggle.setObjectName("flatButton")
        self.notes_toggle.setAutoRaise(True)
        self.notes_toggle.clicked.connect(self._toggle_notes)
        self.notes_toggle.setVisible(False)
        layout.addWidget(self.notes_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.notes_area = QTextEdit()
        self.notes_area.setReadOnly(True)
        self.notes_area.setFixedHeight(120)
        self.notes_area.setVisible(False)
        layout.addWidget(self.notes_area)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.buttons = QDialogButtonBox()
        self.btn_update = self.buttons.addButton(
            "Update", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_later = self.buttons.addButton(
            "Later", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.btn_close = self.buttons.addButton(
            "Close", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.btn_retry = self.buttons.addButton(
            "Retry", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.btn_cancel = self.buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )

        self.btn_update.clicked.connect(self._start_update)
        self.btn_retry.clicked.connect(self._start_check)
        # Custom buttons are not auto-wired to the dialog, so dismissing has to
        # be connected explicitly (otherwise [Close] does nothing).
        self.btn_later.clicked.connect(self.reject)
        self.btn_close.clicked.connect(self.reject)
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(self.buttons)

        # Buttons/checkboxes get a hand cursor from the app-wide filter.
        install_pointer_cursors(QApplication.instance())

        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._staged.connect(self._on_staged)
        self._stage_failed.connect(self._on_stage_failed)

        current = display_version(read_current_version())
        self.current_label.setText(f"Current: {current}")
        self._set_state("checking")
        QTimer.singleShot(0, self._start_check)

    # =========================
    # STATE
    # =========================
    def _set_state(self, state: str):
        self._state = state
        shown = STATE_BUTTONS[state]
        for name, button in (
            ("update", self.btn_update),
            ("later", self.btn_later),
            ("close", self.btn_close),
            ("retry", self.btn_retry),
            ("cancel", self.btn_cancel),
        ):
            button.setVisible(name in shown)

    def _set_status(self, text: str) -> None:
        """Set the status text, reserving the height a wrapped label needs.

        A word-wrapped QLabel is not guaranteed the height it needs inside a
        QVBoxLayout, so longer messages used to be clipped.
        """
        self.status_label.setText(text)
        self._fit_status()

    def _fit_status(self) -> None:
        width = self.status_label.width()
        if width <= 0:
            width = max(self.minimumWidth(), 320)
        needed = self.status_label.heightForWidth(width)
        if needed > 0:
            self.status_label.setMinimumHeight(needed)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_status()

    # =========================
    # RELEASE NOTES (collapse / expand)
    # =========================
    def _set_notes(self, notes: str):
        notes = clean_notes(notes)
        self._notes = notes
        if not notes:
            self._reset_notes()
            return
        self._notes_expanded = False
        self.notes_area.setPlainText(notes)
        self.notes_area.setVisible(False)
        self.notes_toggle.setText(f"What's new {NOTES_ARROW_DOWN}")
        self.notes_toggle.setVisible(True)
        self.adjustSize()

    def _reset_notes(self):
        self._notes = ""
        self._notes_expanded = False
        self.notes_area.clear()
        self.notes_area.setVisible(False)
        self.notes_toggle.setVisible(False)

    def _toggle_notes(self):
        self._notes_expanded = not self._notes_expanded
        arrow = NOTES_ARROW_UP if self._notes_expanded else NOTES_ARROW_DOWN
        self.notes_area.setVisible(self._notes_expanded)
        self.notes_toggle.setText(f"What's new {arrow}")
        self.adjustSize()

    # =========================
    # CHECK
    # =========================
    def _start_check(self):
        self.latest_label.setVisible(False)
        self._reset_notes()
        self.progress.setVisible(False)
        self._set_status("Checking for updates …")
        self._set_state("checking")
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        try:
            info = check_for_update()
        except UpdateError as e:
            self._checked.emit(("error", str(e)))
        except Exception as e:  # noqa: BLE001 - surfaced to the user as text
            self._checked.emit(("error", str(e)))
        else:
            self._checked.emit(("ok", info))

    def _on_checked(self, payload):
        if self._closed:
            return

        status, value = payload
        if status == "error":
            self._set_status(f"Could not check for updates: {value}")
            self._set_state("error")
            return

        self._info = value
        if value.current:
            self.current_label.setText(
                f"Current: {display_version(value.current)}"
            )

        if value.available and value.asset_for_platform() is not None:
            self.latest_label.setText(f"Latest: {display_version(value.latest)}")
            self.latest_label.setVisible(True)

            self._set_notes((value.notes or "").strip())

            if is_frozen():
                self._set_status("A new version is available.")
                self._set_state("available")
            else:
                # Applying would overwrite the source checkout, so only offer it
                # in a packaged build.
                self._set_status(
                    "A new version is available, but updates can only be "
                    "installed from the packaged build."
                )
                self._set_state("uptodate")
        elif value.available:
            self._set_status("No package is available for this platform.")
            self.latest_label.setText(f"Latest: {display_version(value.latest)}")
            self.latest_label.setVisible(True)
            self._set_state("uptodate")
        else:
            self._reset_notes()
            self._set_status("You are running the latest version.")
            self._set_state("uptodate")

    # =========================
    # UPDATE
    # =========================
    def _start_update(self):
        if self._info is None:
            return
        if self._info.asset_for_platform() is None:
            self._set_status("No package is available for this platform.")
            self._set_state("error")
            return

        self._cancel.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self._set_status(
            f"Downloading {display_version(self._info.latest)} …"
        )
        self._set_state("downloading")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            root = prepare_update(
                self._info,
                progress=lambda done, total: self._progress.emit(done, total),
                cancel=self._cancel.is_set,
            )
        except InstallError as e:
            self._stage_failed.emit(e.code or str(e))
            return
        except Exception as e:  # noqa: BLE001 - surfaced to the user as text
            self._stage_failed.emit(str(e) or type(e).__name__)
            return

        self._staged.emit(str(root))

    def _on_progress(self, done: int, total: int):
        if self._closed:
            return

        version = display_version(self._info.latest)
        if total > 0:
            percent = int(done * 100 / total)
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self._set_status(
                f"Downloading {version} … {percent}% "
                f"({done / 1048576:.1f} / {total / 1048576:.1f} MB)"
            )
        else:
            self.progress.setRange(0, 0)
            self._set_status(f"Downloading {version} …")

    def _on_staged(self, path: str):
        if self._closed:
            return

        self.staged_root = Path(path)
        self.staged_version = self._info.latest
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._set_status(
            "The update is ready. FileForge will close and restart to finish "
            "installing it."
        )
        self._set_state("ready")
        QTimer.singleShot(1200, self.accept)

    def _on_stage_failed(self, message: str):
        if self._closed:
            return

        if message == "no_package":
            text = "No package is available for this platform."
        elif message == "cancelled":
            text = "Update cancelled."
        else:
            text = f"Update failed: {message}"

        self.progress.setVisible(False)
        self._set_status(text)
        self._set_state("error")

    # =========================
    # CLOSE
    # =========================
    def reject(self):
        self._cancel.set()
        self._closed = True
        super().reject()

    def accept(self):
        self._closed = True
        super().accept()
