from __future__ import annotations

import os
from pathlib import Path

import pytest

import build

ROOT = Path(__file__).resolve().parents[1]


def test_ensure_pyinstaller_is_a_noop_when_available(monkeypatch):
    monkeypatch.setattr(build, "pyinstaller_available", lambda: True)
    called = []
    monkeypatch.setattr(build.subprocess, "check_call", lambda *a, **k: called.append(a))
    build.ensure_pyinstaller()  # must not raise, must not install
    assert called == []


def test_ensure_pyinstaller_refuses_outside_a_virtualenv(monkeypatch, capsys):
    monkeypatch.setattr(build, "pyinstaller_available", lambda: False)
    monkeypatch.setattr(build, "in_virtualenv", lambda: False)
    called = []
    monkeypatch.setattr(build.subprocess, "check_call", lambda *a, **k: called.append(a))

    with pytest.raises(SystemExit) as excinfo:
        build.ensure_pyinstaller()

    assert excinfo.value.code == 1
    assert called == []  # never installs into the system Python
    message = capsys.readouterr().err
    assert "virtual environment" in message
    assert ".venv" in message


def test_ensure_pyinstaller_installs_inside_a_virtualenv(monkeypatch):
    monkeypatch.setattr(build, "pyinstaller_available", lambda: False)
    monkeypatch.setattr(build, "in_virtualenv", lambda: True)
    called = []
    monkeypatch.setattr(build.subprocess, "check_call", lambda cmd, **k: called.append(cmd))

    build.ensure_pyinstaller()

    assert len(called) == 1
    assert called[0][1:] == ["-m", "pip", "install", "pyinstaller"]


def test_ensure_pyinstaller_reports_a_failed_install(monkeypatch, capsys):
    import subprocess

    monkeypatch.setattr(build, "pyinstaller_available", lambda: False)
    monkeypatch.setattr(build, "in_virtualenv", lambda: True)

    def boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(build.subprocess, "check_call", boom)

    with pytest.raises(SystemExit) as excinfo:
        build.ensure_pyinstaller()

    assert excinfo.value.code == 1
    assert "Could not install PyInstaller" in capsys.readouterr().err


def test_in_virtualenv_matches_the_test_interpreter():
    # The suite runs from the project venv, so this must be True there.
    assert build.in_virtualenv() is True
    assert build.pyinstaller_available() is True


def test_start_scripts_bootstrap_and_run():
    # Dependencies come from pyproject.toml, so the launcher bootstraps the venv itself.
    sh = (ROOT / "start.sh").read_text()
    assert ".venv" in sh
    assert 'pip install -e "."' in sh
    assert "run.py" in sh

    bat = (ROOT / "start.bat").read_text()
    assert ".venv" in bat
    assert 'pip install -e "."' in bat
    assert "run.py" in bat

    assert os.access(ROOT / "start.sh", os.X_OK)


def test_no_redundant_wrapper_scripts():
    # setup.*, build.* wrappers and the requirements mirrors were removed: pyproject.toml
    # is the single source of dependencies, and build.py is run directly.
    for name in (
        "setup.sh",
        "setup.ps1",
        "build.sh",
        "build.ps1",
        "requirements.txt",
        "requirements-dev.txt",
    ):
        assert not (ROOT / name).exists(), f"{name} should have been removed"



def test_build_bundles_app_assets(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(build, "ensure_pyinstaller", lambda: None)
    monkeypatch.setattr(
        build.subprocess, "call", lambda cmd, **k: captured.setdefault("cmd", cmd) and 0
    )

    assert build.build("FileForge", False, True) == 0

    cmd = captured["cmd"]
    assert "--onedir" in cmd
    assert cmd[-1] == str(ROOT / "run.py")

    value = cmd[cmd.index("--add-data") + 1]
    source, destination = value.split(os.pathsep)
    # Icons are resolved relative to the app package, so the bundle must mirror it.
    assert destination == "app/assets"
    assert source == str(ROOT / "app" / "assets")
    # A relative source would be resolved against the spec file instead.
    assert os.path.isabs(source)


