from __future__ import annotations

import os
import sys

from app.utils.process_utils import child_env


def test_child_env_drops_the_pyinstaller_bundle(monkeypatch):
    # Reproduces the shipped bug: ffmpeg inherited LD_LIBRARY_PATH pointing at the
    # bundle, loaded the bundled libfontconfig and died with
    # "libass.so.9: undefined symbol: FcConfigSetDefaultSubstitute".
    monkeypatch.setattr(sys, "_MEIPASS", "/opt/app/_internal", raising=False)
    monkeypatch.setenv(
        "LD_LIBRARY_PATH", "/opt/app/_internal" + os.pathsep + "/usr/lib"
    )

    entries = child_env()["LD_LIBRARY_PATH"].split(os.pathsep)

    assert "/opt/app/_internal" not in entries
    assert "/usr/lib" in entries  # the system's own path is kept


def test_child_env_drops_the_variable_when_it_only_holds_the_bundle(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/opt/app/_internal", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/app/_internal")

    assert "LD_LIBRARY_PATH" not in child_env()


def test_child_env_removes_the_bundle_from_path(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", "/opt/app/_internal", raising=False)
    monkeypatch.setenv("PATH", "/opt/app/_internal" + os.pathsep + "/usr/bin")

    assert child_env()["PATH"] == "/usr/bin"


def test_child_env_is_untouched_outside_a_bundle(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/somewhere/else")

    assert child_env()["LD_LIBRARY_PATH"] == "/somewhere/else"
