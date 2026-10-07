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


def test_in_virtualenv_reads_the_environment(monkeypatch):
    # Environment-independent: assert how the check is made, not that this
    # particular interpreter happens to be a venv (CI's toolcache Python is not).
    monkeypatch.setenv("VIRTUAL_ENV", "/some/venv")
    assert build.in_virtualenv() is True

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(build.sys, "prefix", "/usr")
    monkeypatch.setattr(build.sys, "base_prefix", "/usr")
    assert build.in_virtualenv() is False

    monkeypatch.setattr(build.sys, "base_prefix", "/usr/lib/venv-base")
    assert build.in_virtualenv() is True


def test_pyinstaller_available_is_a_bool():
    assert isinstance(build.pyinstaller_available(), bool)


def test_remove_unbundled_libs_keeps_everything_else(tmp_path):
    # A foreign libxkbcommon segfaults in xkb_state_key_get_layout() on the host's
    # X server, and a foreign libfontconfig cannot read the host's font config.
    internal = tmp_path / "_internal"
    internal.mkdir()
    for name in (
        "libxkbcommon.so.0",
        "libxkbcommon-x11.so.0",
        "libfontconfig.so.1",
        "libQt6Core.so.6",
        "libfreetype.so.6",
    ):
        (internal / name).write_text("x", encoding="utf-8")

    removed = build.remove_unbundled_libs(tmp_path)

    assert sorted(removed) == [
        "libfontconfig.so.1",
        "libxkbcommon-x11.so.0",
        "libxkbcommon.so.0",
    ]
    assert (internal / "libQt6Core.so.6").exists()
    assert (internal / "libfreetype.so.6").exists()


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

    # Collect every --add-data source:dest pair.
    datas = {}
    for index, item in enumerate(cmd):
        if item == "--add-data":
            source, destination = cmd[index + 1].split(os.pathsep)
            datas[destination] = source

    # Icons are resolved relative to the app package, so the bundle mirrors it.
    assert datas["app/assets"] == str(ROOT / "app" / "assets")
    # version.json is read at runtime by the updater; bundled data lands in _internal.
    assert datas["."] == str(ROOT / "version.json")

    for source in datas.values():
        # A relative source would be resolved against the spec file instead.
        assert os.path.isabs(source)


