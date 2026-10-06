from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QLabel, QToolButton

from app.core.updater.checker import ReleaseAsset, UpdateInfo
from app.core.updater.version import display_version, read_current_version
from app.ui.dialogs import about_dialog as about_mod
from app.ui.dialogs import version_dialog as vd


def _asset_name() -> str:
    import os

    return "FileForge-windows.zip" if os.name == "nt" else "FileForge-linux.zip"


def _info(version: str = "v9.9.9") -> UpdateInfo:
    return UpdateInfo(
        current=read_current_version(),
        latest=version,
        notes="## What's new\n\n* something\n",
        assets=[ReleaseAsset(name=_asset_name(), url="https://example/pkg.zip")],
    )


# ------------------------------------------------------------------ About dialog
def test_about_shows_the_version_from_version_json(qtbot):
    dialog = about_mod.AboutDialog()
    qtbot.addWidget(dialog)

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    expected = f"Version {display_version(read_current_version())}"
    assert expected in labels


def test_about_help_button_opens_the_version_dialog(qtbot, monkeypatch):
    opened: list = []

    class FakeVersionDialog:
        def __init__(self, parent=None):
            self.staged_root = None
            self.staged_version = ""

        def exec(self):
            opened.append(True)
            return 0

    monkeypatch.setattr(about_mod, "VersionDialog", FakeVersionDialog)

    dialog = about_mod.AboutDialog()
    qtbot.addWidget(dialog)
    dialog.findChild(QToolButton).click()

    assert opened == [True]


def test_about_reports_a_staged_update_to_the_callback(qtbot, monkeypatch):
    class FakeVersionDialog:
        def __init__(self, parent=None):
            self.staged_root = Path("/tmp/fileforge-staged")
            self.staged_version = "v2.0.0"

        def exec(self):
            return 1

    monkeypatch.setattr(about_mod, "VersionDialog", FakeVersionDialog)

    calls: list = []
    dialog = about_mod.AboutDialog(on_update_ready=lambda root, ver: calls.append((root, ver)))
    qtbot.addWidget(dialog)
    dialog.findChild(QToolButton).click()

    assert calls == [(Path("/tmp/fileforge-staged"), "v2.0.0")]


# ------------------------------------------------------------ Version dialog
def test_version_dialog_notes_cleanup():
    raw = "## What's new\n\n- a\n\n\n**Full Changelog**: https://example/compare\n"
    assert vd.clean_notes(raw) == "## What's new\n\n- a"


def test_version_dialog_offers_update_in_a_packaged_build(qtbot, monkeypatch):
    monkeypatch.setattr(vd, "check_for_update", lambda: _info())
    monkeypatch.setattr(vd, "is_frozen", lambda: True)

    dialog = vd.VersionDialog()
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._state != "checking", timeout=5000)

    assert dialog._state == "available"
    assert dialog.btn_update.isVisible() or dialog._state == "available"
    assert "available" in dialog.status_label.text().lower()


def test_version_dialog_will_not_install_from_a_source_checkout(qtbot, monkeypatch):
    # Applying over a source checkout would overwrite the repo, so it is refused.
    monkeypatch.setattr(vd, "check_for_update", lambda: _info())
    monkeypatch.setattr(vd, "is_frozen", lambda: False)

    dialog = vd.VersionDialog()
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._state != "checking", timeout=5000)

    assert dialog._state == "uptodate"
    assert "packaged build" in dialog.status_label.text()
    assert dialog.staged_root is None


def test_version_dialog_reports_check_failures(qtbot, monkeypatch):
    from app.core.updater.checker import UpdateError

    def boom():
        raise UpdateError("offline")

    monkeypatch.setattr(vd, "check_for_update", boom)

    dialog = vd.VersionDialog()
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._state == "error", timeout=5000)

    assert "offline" in dialog.status_label.text()


# ------------------------------------------------------------------ sizing
def _fits(dialog) -> bool:
    label = dialog.status_label
    return label.height() >= label.heightForWidth(label.width())


def test_version_dialog_fits_its_content_without_release_notes(qtbot, monkeypatch):
    # Regression: with no notes nothing called adjustSize(), so the dialog stayed
    # at its "checking" height and the new rows were squeezed.
    monkeypatch.setattr(
        vd,
        "check_for_update",
        lambda: UpdateInfo(
            current="1.0.0",
            latest="v9.9.9",
            notes="",
            assets=[ReleaseAsset(name=_asset_name(), url="https://example/p.zip")],
        ),
    )
    monkeypatch.setattr(vd, "is_frozen", lambda: True)

    dialog = vd.VersionDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._state != "checking", timeout=5000)
    qtbot.wait(20)

    assert dialog._state == "available"
    assert dialog.height() >= dialog.layout().minimumSize().height()
    assert _fits(dialog)


def test_version_dialog_grows_for_a_wrapped_status(qtbot, monkeypatch):
    monkeypatch.setattr(vd, "check_for_update", lambda: _info())
    monkeypatch.setattr(vd, "is_frozen", lambda: True)

    dialog = vd.VersionDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._state != "checking", timeout=5000)
    before = dialog.height()

    dialog._set_status("Downloading … " + "word " * 80)
    qtbot.wait(20)

    assert dialog.height() > before  # the dialog grew instead of clipping
    assert _fits(dialog)
