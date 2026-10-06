# FileForge — File Converter

A desktop file conversion application written in Python with a PyQt6 interface.

- **Images** — Pillow (`png`, `jpg`, `webp`, `bmp`, `tiff`, `ico`)
- **Documents** — LibreOffice headless (external tool): `doc`, `docx`, `odt`, `rtf`,
  `txt` → `pdf` and other document targets
- **Audio** — FFmpeg (external tool): `mp3`, `wav`, `flac`, `aac`, `ogg`, `m4a`;
  also extracts audio from video (`mp4`/`mkv`/`webm`/`mov`/`avi` → audio)
- **Video** — FFmpeg (external tool): `mp4`, `mkv`, `webm`, `mov`, `avi`

Supported platforms: **Windows and Linux**.

## Architecture

```text
Add files / Drag & Drop
        ↓
Detect source format
        ↓
Select target format (per file)
        ↓
Convert All
        ↓
Preflight: resolve output path, select engine, validate, resolve conflicts
        ↓
Job Queue
        ↓
Worker (QThreadPool)
        ↓
Converter Engine
        ↓
Output file
```

The GUI contains no conversion logic. Converters sit behind a single interface
(`app/converters/base.py`), so new formats and engines are added without touching the
UI or the queue.

## Requirements

- Python 3.10+
- For documents: LibreOffice (`soffice`)
- For audio/video: FFmpeg

External tools are detected at startup. A missing tool disables only the conversions
that need it; the rest of the app keeps working.

## Setup (virtual environment)

Always develop and run inside a virtual environment. Never install the project's
dependencies into the system Python.

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# then, in both cases
pip install -e ".[dev]"
python run.py
```

Notes:

- Python dependencies (`PyQt6`, `Pillow`, `platformdirs`) are declared in
  `pyproject.toml`, which is the single source of truth. Extras: `dev` (pytest,
  pytest-qt) and `build` (PyInstaller). The venv can be rebuilt from it at any time.
- `.venv/` is git-ignored. Never commit it.
- FFmpeg and LibreOffice are system-level programs. They are not pip-installed and are
  not part of the venv.

## Running

`start.sh` / `start.bat` create the venv, install the runtime dependencies from
`pyproject.toml` if they are missing, then launch the app:

```bash
./start.sh          # Linux / macOS
```

```bat
start.bat           :: Windows
```

Or run it manually inside the venv with `python run.py`.

## Building a standalone executable

`build.py` packages the app with PyInstaller on both Windows and Linux. It must run
from the virtual environment — build tools are never installed into the system Python:

```bash
.venv/bin/python build.py           # Linux / macOS (no activation needed)
source .venv/bin/activate && python build.py
```

```bat
.venv\Scripts\python build.py       :: Windows
```

```bash
python build.py                  # folder build -> dist/FileForge/
python build.py --onefile        # single-file executable
python build.py --name MyApp     # custom name
python build.py --console        # keep a console window on Windows
```

Install the build dependency once with `pip install -e ".[build]"` (PyInstaller);
`build.py` also installs it into the venv automatically when it is missing. Running
`build.py` with the system Python exits with instructions instead of trying to install
PyInstaller system-wide.

On Windows the build is windowed by default (`app/assets/icons/fileforge.ico` is used
as the icon when present). The app's icons (`app/assets/icons`) are bundled so they
resolve inside the packaged app. Build output (`build/`, `dist/`, `*.spec`) is
git-ignored.

## Using

- **Per-file target**: click the format badge in a queue row (or right-click →
  *Convert to…*) to pick the target format; unavailable targets are greyed out with a
  reason.
- **Per-file options**: double-click a row (or right-click → *Options…*) to edit
  quality, bitrate, resolution, etc. The dialog is generated from each converter's
  `options_schema()`, so it adapts to the selected conversion.
- **Preview**: selecting an image shows a thumbnail; the queue and preview never block.
- **Errors**: right-click → *Show error…* for the full message.
- **Cancel vs Remove**: right-click → *Cancel* stops a waiting/converting job but keeps it
  in the queue (status *Cancelled*), so **Convert All** can run it again. *Remove* deletes
  the row (cancelling it first if it is running).
- **Theme**: Settings → Theme (follow system / light / dark).
- **Settings help**: every setting has a **?** button next to its label that opens a
  short explanation.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Add files |
| `F5` / `Ctrl+R` | Convert All |
| `Ctrl+L` | Clear queue |
| `Delete` | Remove selected rows |
| `Ctrl+,` | Settings |
| `F1` | About |
| `Ctrl+Q` | Quit |

## Running tests

```bash
pytest
```

## Configuration and logs

Stored in the per-user directory via `platformdirs` (not in the repository):

- Linux: `~/.config/FileForge/`
- Windows: `%APPDATA%\FileForge\`

## Roadmap

- **v0.1** — Image converter (PNG ↔ JPG/WEBP/ICO, batches, cancel, atomic writes)
- **v0.2** — Documents (LibreOffice): headless conversion, isolated profile per worker,
  timeout, cancellable process, manual tool path + Re-detect
- **v0.3** — Audio (FFmpeg): formats, `-progress pipe:1` parse, cancellable process,
  atomic output
- **v0.4** — Video (FFmpeg): `mp4`/`mkv`/`webm`/`mov`/`avi`, per-container codec
  defaults (H.264/AAC, VP9/Opus, MPEG-4/MP3), tuned VP9 (`-row-mt`, `-cpu-used`),
  cancellable process, shared FFmpeg runner
- **v0.5** — UX: per-file options dialog generated from `options_schema()`, image
  preview, light/dark/system theme, keyboard shortcuts, error details
- **v1.0** — Stable release, comprehensive tests, packaging
