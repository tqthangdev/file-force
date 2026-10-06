# FileForge — File Converter

A desktop file conversion application written in Python with a PyQt6 interface.

## Features

* **Images** — PNG, JPG, WebP, BMP, TIFF, ICO
* **Documents** — DOC, DOCX, ODT, RTF, TXT, PDF and other document formats
* **Audio** — MP3, WAV, FLAC, AAC, OGG, M4A
* **Video** — MP4, MKV, WebM, MOV, AVI
* Extract audio from video
* Per-file conversion settings
* Drag & drop
* Batch conversion
* Light / dark / system themes

Supported platforms: **Windows and Linux**.

## Release

Prebuilt standalone builds (Windows / Linux) are published on [GitHub Releases](https://github.com/tqthangdev/file-forge/releases) — no Python installation required. Pushing a `v*` tag triggers the CI build.

## Requirements

* Python 3.10+
* [LibreOffice](https://www.libreoffice.org/) — document conversion
* [FFmpeg](https://ffmpeg.org/) — audio and video conversion

## Setup

Create a virtual environment and install the dependencies:

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

Run the application:

```bash
python run.py
```

You can also use the provided startup scripts:

```bash
./start.sh       # Linux / macOS
```

```bash
start.bat       # Windows
```

## Build

FileForge can be packaged as a standalone executable with PyInstaller.

```bash
python build.py
```

For a single executable:

```bash
python build.py --onefile
```

Build output is placed in `dist/`.

## Usage

1. Add files or drag and drop them into the queue.
2. Select the target format for each file.
3. Adjust conversion options if needed.
4. Click **Convert All**.

Right-click a queue item for additional actions such as **Convert to…**, **Options…**, **Show error…**, **Cancel**, and **Remove**.

## Keyboard Shortcuts

| Shortcut | Action               |
| -------- | -------------------- |
| `Ctrl+O` | Add files            |
| `Ctrl+R` | Convert All          |
| `Ctrl+L` | Clear queue          |
| `Delete` | Remove selected rows |
| `Ctrl+,` | Settings             |
| `Ctrl+Q` | Quit                 |

## Tests

```bash
pytest
```

## Configuration

Application settings and logs are stored in the user's configuration directory:

* **Linux:** `~/.config/FileForge/`
* **Windows:** `%APPDATA%\FileForge\`

## Releases and updates

Releases are built by `.github/workflows/build.yml`: pushing a tag `v*` builds the
Linux and Windows packages and attaches them to a GitHub Release. In the app,
**About → ?** opens the version dialog, which checks for a newer release, shows the
release notes and can download and install it.

Bump `version.json` before tagging — a package whose `version.json` does not match the
release tag is refused:

```bash
# version.json -> {"version": "1.0.1"}
git tag v1.0.1
git push origin v1.0.1
```

How the update works:

* Checking and downloading work anywhere, but **installing** is only offered from a
  packaged build — over a source checkout it would overwrite the repository.
* The app never overwrites itself. It stages the package under `.update/<version>/`
  and starts a separate updater process, which waits for the app to exit, swaps the
  files (keeping a backup and rolling back if verification fails) and relaunches.

