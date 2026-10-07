#!/usr/bin/env python3
"""Build a standalone FileForge executable with PyInstaller.

Works on both Windows and Linux. Run it with the project's virtual environment
Python so PyInstaller builds against the app's dependencies:

    .venv/bin/python build.py           # Linux / macOS
    .venv\\Scripts\\python build.py        # Windows
    python build.py --onefile           # single-file executable
    python build.py --name MyApp        # custom name
    python build.py --console           # keep a console window on Windows

Run it from an activated virtual environment, or call the venv's Python directly.
PyInstaller is installed into the *current* environment on first use, but only when
that environment is a virtualenv — build tools are never installed into the system
Python (see the project README).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Shared libraries that must come from the host system, never from the bundle.
# Shipping another distribution's copies makes system tools (ffmpeg, soffice) load
# an incompatible ABI — e.g. "libass.so.9: undefined symbol:
# FcConfigSetDefaultSubstitute" when ffmpeg picks up the bundled libfontconfig —
# and it can break Qt's font handling too. PyInstaller collects them because the
# build machine's Qt links against them.
_SYSTEM_LIB_PREFIXES = (
    "libfontconfig.so",
    "libfreetype.so",
    "libharfbuzz.so",
    "libfribidi.so",
    "libglib-2.0.so",
    "libjson-glib-1.0.so",
    "libX11.so",
    "libX11-xcb.so",
    "libxcb",
    "libxkbcommon",
    "libwayland-",
)


def prune_bundled_system_libs(dist_dir: Path) -> list[str]:
    """Delete bundled copies of system libraries; returns the names removed."""
    internal = dist_dir / "_internal"
    if not internal.is_dir():
        return []

    removed = []
    for library in sorted(internal.glob("lib*.so*")):
        if library.name.startswith(_SYSTEM_LIB_PREFIXES):
            library.unlink()
            removed.append(library.name)
    return removed


def in_virtualenv() -> bool:
    """True when this interpreter belongs to a virtual environment."""
    if os.environ.get("VIRTUAL_ENV"):
        return True
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def pyinstaller_available() -> bool:
    return importlib.util.find_spec("PyInstaller") is not None


def _venv_executable() -> str:
    if sys.platform == "win32":
        return r".venv\Scripts\python.exe"
    return "./.venv/bin/python"


def _venv_hint() -> str:
    lines = [
        "PyInstaller is not available in the Python running this script:",
        f"    {sys.executable}",
        "",
        "Build inside the project's virtual environment — do not install build",
        "tools into the system Python.",
        "",
    ]
    if (ROOT / ".venv").is_dir():
        lines += [
            "The project venv exists, so run the build with it directly:",
            f"    {_venv_executable()} build.py",
            "",
        ]
    lines += [
        "or activate the virtual environment first:",
    ]
    if sys.platform == "win32":
        lines.append(r"    .venv\Scripts\activate   then   python build.py")
    else:
        lines.append("    source .venv/bin/activate   then   python build.py")
    return "\n".join(lines)


def ensure_pyinstaller() -> None:
    """Make sure PyInstaller is usable, installing it only into a virtualenv."""
    if pyinstaller_available():
        return

    if not in_virtualenv():
        print(_venv_hint(), file=sys.stderr)
        raise SystemExit(1)

    print("PyInstaller not found — installing it into the current environment ...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    except subprocess.CalledProcessError as exc:
        print(
            f"\nCould not install PyInstaller (pip exited with {exc.returncode}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def build(name: str, onefile: bool, console: bool) -> int:
    ensure_pyinstaller()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        "--paths",
        str(ROOT),
        "--onefile" if onefile else "--onedir",
    ]

    if sys.platform == "win32" and not console:
        command.append("--windowed")
        icon = ROOT / "app" / "assets" / "icons" / "fileforge.ico"
        if icon.exists():
            command += ["--icon", str(icon)]

    # The app resolves its icons relative to the package (app/ui/assets.py), so the
    # bundle must keep them at the same relative path: <bundle>/app/assets/icons.
    assets = ROOT / "app" / "assets"
    if assets.is_dir() and any(assets.iterdir()):
        command += ["--add-data", f"{assets}{os.pathsep}app/assets"]

    # version.json is read at runtime (app/core/updater/paths.py). Bundled data lands
    # in the onedir `_internal` folder, which is where it is looked up.
    version_file = ROOT / "version.json"
    if version_file.is_file():
        command += ["--add-data", f"{version_file}{os.pathsep}."]

    command.append(str(ROOT / "run.py"))

    print("Running:", " ".join(command))
    exit_code = subprocess.call(command, cwd=str(ROOT))

    if exit_code == 0 and sys.platform != "win32":
        removed = prune_bundled_system_libs(ROOT / "dist" / name)
        if removed:
            print(f"\nRemoved {len(removed)} bundled system librar(y/ies) that must "
                  f"come from the host:")
            for library in removed:
                print("   -", library)

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a standalone FileForge executable with PyInstaller."
    )
    parser.add_argument(
        "--onefile", action="store_true", help="build a single-file executable"
    )
    parser.add_argument("--name", default="FileForge", help="executable name")
    parser.add_argument(
        "--console",
        action="store_true",
        help="keep a console window on Windows (default: windowed)",
    )
    args = parser.parse_args()

    exit_code = build(args.name, args.onefile, args.console)
    if exit_code == 0:
        print(f"\nBuild finished. Output is in: {ROOT / 'dist'}")
    else:
        print(f"\nBuild failed with exit code {exit_code}.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
