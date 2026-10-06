# File Converter — Project Structure & Implementation Plan (v2.1)

> Changes from v2:
>
> - `convert()` takes a `ConversionContext`, not a `ConversionJob`. Converters never see job state.
> - New **preflight** step: output paths are resolved, validated and conflict-checked before
>   any job enters the queue. Workers only execute.
> - `converter.validate(context)` reports problems before conversion starts.
> - `ConversionJob` is pure data; `engine` renamed to `selected_engine` (a name, never an object).
> - Python dependencies (Pillow) are separated from external tools (FFmpeg, LibreOffice).
> - Removed from the initial structure: `history.py`, `document_msoffice.py`, `document_basic.py`.
>   They are listed under "Later, only on real demand".
> - Roadmap tightened: v0.1 image, v0.2 LibreOffice, v0.3 audio, v0.4 video.
> - `options_schema()` is planned but deferred until the options dialog exists.
> - PyQt6 is the chosen toolkit. No toolkit alternatives in this document.

---

## 1. Project overview

A desktop file conversion application built with:

- Python
- PyQt6
- Pillow: image conversion
- FFmpeg: audio/video conversion (external tool)
- LibreOffice: document conversion (external tool)

Supported platforms: **Windows and Linux**.

Core flow:

```text
Add files / Drag & Drop
        ↓
Detect source format
        ↓
Select target format (per file)
        ↓
Convert All
        ↓
Preflight: resolve output path, resolve conflicts, validate
        ↓
Job Queue
        ↓
Worker (QThreadPool)
        ↓
Converter Engine
        ↓
Output file
```

The GUI contains no conversion logic. Converters sit behind one interface, so new formats
and new engines are added without touching the UI or the queue.

---

## 2. Directory structure

```text
file-converter/
│
├── run.py
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
│
├── app/
│   ├── __init__.py
│   │
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── drop_area.py
│   │   ├── queue_view.py
│   │   ├── queue_model.py          # QAbstractListModel
│   │   ├── queue_delegate.py
│   │   ├── convert_dialog.py       # later (needs options_schema)
│   │   ├── settings_dialog.py
│   │   └── about_dialog.py
│   │
│   ├── core/
│   │   ├── converter_manager.py
│   │   ├── format_registry.py
│   │   ├── file_detector.py
│   │   ├── preflight.py
│   │   ├── job_manager.py
│   │   └── worker.py
│   │
│   ├── converters/
│   │   ├── base.py
│   │   ├── image.py
│   │   ├── audio.py                # v0.3
│   │   ├── video.py                # v0.4
│   │   └── document_libreoffice.py # v0.2
│   │
│   ├── models/
│   │   ├── conversion_job.py
│   │   ├── conversion_context.py
│   │   └── file_info.py
│   │
│   ├── services/
│   │   ├── settings.py
│   │   ├── external_tools.py
│   │   └── logging_setup.py
│   │
│   └── utils/
│       ├── file_utils.py
│       ├── process_utils.py
│       └── format_utils.py
│
├── assets/
│   └── icons/
│
└── tests/
    ├── fakes.py                    # FakeConverter
    ├── test_file_detector.py
    ├── test_format_registry.py
    ├── test_preflight.py
    ├── test_converter_manager.py
    ├── test_image_converter.py
    └── test_job_manager.py
```

**Create files when they are first needed.** This structure is the target shape, not a
checklist. v0.1 can start with fewer files (for example no `audio.py`, `video.py`,
`document_libreoffice.py`, `convert_dialog.py`) and add them in their own milestones.

Config and logs live in the per-user directory (via `platformdirs`), not in the repo.

---

## 3. Responsibilities

### `run.py`

Create `QApplication`, set up logging, load settings, detect external tools, create
`MainWindow`, start the event loop. Almost no logic.

### `app/ui/`

Display and user input only. The UI never calls Pillow, FFmpeg or LibreOffice.

- **`main_window.py`**: layout; forwards user actions to `JobManager`.
- **`drop_area.py`**: accepts files and folders, emits `files_dropped = pyqtSignal(list)`.
  Folder scanning (especially recursive) runs in a worker.
- **`queue_model.py`**: `QAbstractListModel` of jobs; emits `dataChanged` on status/progress.
- **`queue_view.py` / `queue_delegate.py`**: render one job row (name, source → target,
  size, target dropdown, progress, status). Pure display.
- **`settings_dialog.py`**: output settings, worker count, external tool paths.
- **`convert_dialog.py`**: later; generated from `options_schema()`.

### `app/core/`

Business logic: sections 4 to 8.

### `app/converters/`, `app/models/`, `app/services/`, `app/utils/`

Engines, data classes, application services, helpers.

---

## 4. Models

### `FileInfo`

```python
@dataclass
class FileInfo:
    path: Path
    name: str
    extension: str
    format: str
    category: str
    size: int
```

### `ConversionJob` — data only

```python
class JobStatus(Enum):
    WAITING = "waiting"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"       # no available engine, or failed preflight

@dataclass
class ConversionJob:
    source: Path
    source_format: str
    target_format: str
    output: Path | None = None        # resolved by preflight
    options: dict = field(default_factory=dict)

    selected_engine: str | None = None   # engine NAME, never a converter object
    status: JobStatus = JobStatus.WAITING
    progress: int = 0
    error: str | None = None
```

A job holds data and results. It does not hold converter objects, threads or processes.

### `ConversionContext` — what a converter receives

```python
@dataclass
class ConversionContext:
    source: Path
    output: Path
    options: dict
    progress_callback: Callable[[int], None]
    cancel_event: threading.Event
```

The worker builds a context from a job. Converters know nothing about `status`,
`selected_engine` or `error`, so they stay small and easy to test.

---

## 5. Converter interface

`app/converters/base.py` is the **only** place the contract is defined.

```python
class BaseConverter:
    name: str = ""
    priority: int = 0         # higher wins when several engines support the same pair

    def supported_pairs(self) -> set[tuple[str, str]]:
        """Capability: every (source_format, target_format) this engine can do."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """False if a required external tool is missing."""
        raise NotImplementedError

    def unavailable_reason(self) -> str | None:
        return None

    def max_parallel_jobs(self) -> int:
        return 2

    def validate(self, source_format, target_format, source: Path, options: dict) -> list[str]:
        """Return human-readable problems, or [] if the job is fine.
        Example: 'ICO images cannot exceed 256×256.'"""
        return []

    def convert(self, context: ConversionContext) -> Path:
        """Do the conversion. Returns the final output path."""
        raise NotImplementedError
```

Planned, **deferred until the options dialog exists**:

```python
def options_schema(self, source_format, target_format) -> dict:
    # e.g. {"quality": {"type": "int", "min": 1, "max": 100, "default": 90}}
    # convert_dialog.py generates its widgets from this.
```

Do not build `options_schema()` in v0.1. v0.1 uses fixed defaults.

---

## 6. Format registry

Two different kinds of information, kept separate:

| Information | Where it lives | Example |
|---|---|---|
| **Capability**: what can be converted to what | each converter's `supported_pairs()` | `("png", "jpg")` |
| **Format metadata**: facts about a format | static `FORMAT_INFO` | extensions, MIME, display name, category |

These are not duplicates. A converter should not have to declare that JPEG is called "JPEG"
or that `.jpeg` is an extension of `jpg`.

```python
FORMAT_INFO = {
    "jpg": {
        "display_name": "JPEG",
        "category": "image",
        "extensions": [".jpg", ".jpeg"],
        "mime": "image/jpeg",
    },
    ...
}
```

`FormatRegistry` is built at startup from the registered converters plus `FORMAT_INFO`. It
answers:

- Which targets exist for a given source format?
- Which engines can do a pair, ordered by priority, and which of them are available?
- Why is a pair disabled (tool missing)?

Several engines may serve one pair (for example `docx → pdf` could one day have both
LibreOffice and Word). `ConverterManager` chooses the highest-priority **available** engine,
unless the user forces one in Settings. In v0.2 each pair has one engine; the structure just
does not forbid more.

Adding `SVG → PNG` means one converter plus one `FORMAT_INFO` entry. `main_window.py` and
`job_manager.py` are untouched.

---

## 7. Preflight (`core/preflight.py`)

Policy lives here, not in workers.

Triggered when the user presses **Convert All** (not when a file is added, because the user
may still change the output folder or target format).

For each job, in order:

```text
1. Resolve output path        (output mode, folder, suffix, extension)
2. Select engine              (ConverterManager; no engine → BLOCKED with reason)
3. Validate                   (converter.validate(...) → problems → BLOCKED with message)
4. Resolve conflicts
      a. against existing files on disk  (ask / overwrite / skip / rename automatically)
      b. against other jobs in the same batch
```

Details:

- **Conflicts within the batch** must be caught. `a.png → a.webp` and `a.jpg → a.webp` would
  both write `a.webp`. Resolve with the same conflict mode (usually auto-rename).
- **"Ask" mode is answered here**, with a dialog on the GUI thread **before** the queue
  starts. Workers never ask the user anything.
- Jobs that fail preflight become `BLOCKED` with an error message; the rest of the batch
  still runs.
- Workers still write through a temp file + atomic rename, so if a file appears between
  preflight and write, the result is a clean failure for that job rather than corruption.

After preflight a job is **ready**: `output`, `selected_engine` and `options` are final.

---

## 8. Core layer

### `converter_manager.py`

Picks the engine for a pair (available, highest priority, or user override). The only place
that maps pairs to converters.

### `file_detector.py`

- Normalize extension.
- For images, verify the real format with Pillow (`Image.open().format`), so a PNG renamed
  to `.jpg` is detected correctly.
- Return `FileInfo`.

### `job_manager.py`

Owns the queue: add/remove, start/cancel, track progress, handle completion and errors,
enforce concurrency (global worker count and per-engine `max_parallel_jobs()`). Calls
preflight before queueing.

### `worker.py` — execute only

**Threading model:**

- `QThreadPool` + `QRunnable`; pool size from settings (default 2).
- FFmpeg and LibreOffice run as subprocesses; the worker thread only waits and reads output.
- Pillow runs in the worker thread. If big image batches prove CPU-bound, move image jobs to
  a `ProcessPoolExecutor` later; the converter interface does not change.
- Workers never touch widgets; they emit Qt signals only.

The worker builds a `ConversionContext` from a ready job and calls
`converter.convert(context)`. It contains no output-path logic and no conflict policy.

Signals: `started`, `progress`, `finished`, `error`, `cancelled`.

---

## 9. Image converter (`image.py`, Pillow)

v0.1 scope: **PNG → JPG, PNG → WEBP, PNG → ICO, JPG → PNG** first, then the rest of
PNG / JPG / WEBP / BMP / TIFF / ICO.

Must handle from the start:

- **Alpha → JPG/BMP**: composite onto a background (default white).
- **EXIF orientation**: `ImageOps.exif_transpose`.
- **ICO**: max 256×256; `validate()` reports it, conversion resizes or rejects per option.
- **Color modes**: convert `P`, `LA`, `CMYK`, etc. to what the target supports.
- **Atomic output**: write to a temp file in the target folder, then rename.

Fixed defaults in v0.1 (for example JPEG quality 90). Options come later with
`options_schema()`.

Cancellation: Pillow cannot interrupt a single `save()`. Cancel works **between jobs**.
This is documented behavior.

---

## 10. Audio and video converters (v0.3, v0.4)

FFmpeg, run as a subprocess (list arguments, never a shell string). Progress parsed from
`-progress pipe:1`. Cancel terminates the process.

- Audio: MP3, WAV, FLAC, AAC, OGG, M4A.
- Video: MP4, MKV, WEBM, MOV, AVI.

---

## 11. Document converter (`document_libreoffice.py`, v0.2)

Uses LibreOffice headless through the command line:

```text
soffice --headless --convert-to pdf --outdir <temp_dir> -env:UserInstallation=file:///<profile_dir> <input>
```

Support: DOC, DOCX, ODT, RTF, TXT → PDF, plus DOCX → TXT and similar.

- **`subprocess`, not UNO.** The `uno` module is not pip-installable and complicates
  packaging. Consider `unoserver` only if document batches prove too slow.
- **Separate profile per worker** (`-env:UserInstallation`).
- **`max_parallel_jobs() = 1`** at first.
- **Output naming**: LibreOffice names its own output. Convert into a temp directory, then
  move to the output path chosen by preflight.
- **No percentage progress**: indeterminate progress bar.
- **Timeout** on every job.
- **Windows**: `CREATE_NO_WINDOW`; on cancel, kill the whole process tree
  (`soffice.exe` and `soffice.bin`).
- **Detection**: PATH (`soffice`, `libreoffice`), then default install folders
  (for example `C:\Program Files\LibreOffice\program\soffice.exe`), then the path set in
  Settings.

---

## 12. Dependencies and external tools (`external_tools.py`)

Two different kinds, with different lifecycles.

```text
Python dependencies (part of the app's environment)
    Pillow          ✓

External tools (runtime dependencies, detected)
    FFmpeg          ✓ /usr/bin/ffmpeg
    LibreOffice     ✕ not found     [ Browse... ]  [ Re-detect ]
```

- Python dependencies are declared in `pyproject.toml`. A missing one is an installation
  error, not a runtime state.
- External tools are detected at startup and on demand (**Re-detect**, no restart).
- A missing tool disables **only** the pairs that need it.
- Each tool can be given a manual path in Settings (essential on Windows).
- Detection feeds `converter.is_available()`.

When LibreOffice is missing: image/audio/video keep working; a dropped `.docx` is accepted
but its job is `BLOCKED` with *"Document conversion needs LibreOffice"* and a link to
Settings; unsupported target formats are greyed out.

---

## 13. Application behavior

- **Output modes**: same folder, custom folder, custom subfolder; optional suffix.
- **Conflict modes**: ask, overwrite, skip, rename automatically (resolved in preflight).
- **Per-file target format**: each file has its own target; never one target for all.
- **Drag & drop**: files, folders, multiple of each; optional recursive import (scanned in
  a worker).
- **Batch**: large batches supported; default 2 workers; never one worker per CPU core by
  default.
- **Cancellation**: Pillow between jobs; FFmpeg terminate process; LibreOffice terminate the
  specific process tree. A cancelled job is `CANCELLED`, never `COMPLETED`.
- **Errors**: per job; the queue continues.

---

## 14. Cross-platform notes (Windows + Linux)

| Topic | Linux | Windows |
|---|---|---|
| Config / log location | `~/.config/<app>` | `%APPDATA%\<app>` |
| Finding FFmpeg | `shutil.which("ffmpeg")` | often not in PATH; also check user-set path |
| Finding LibreOffice | `libreoffice` / `soffice` | usually not in PATH; check default install folders |
| Console window on subprocess | none | `creationflags=CREATE_NO_WINDOW` |
| Killing process trees | `terminate()` usually enough | kill the whole tree |
| Packaging | AppImage / Flatpak / .deb | PyInstaller + installer; decide whether to bundle FFmpeg |

Rules: `pathlib.Path` everywhere; `platformdirs` for user directories; subprocess arguments
as a list; test paths with spaces and Vietnamese diacritics on both systems.

### Development environment: use a virtual environment (venv)

Always develop and run the app inside a **venv**. Never install the project's Python
dependencies directly into the system Python.

Why:

- **Linux**: system Python is managed by the OS package manager. Installing with `pip`
  system-wide can break system tools, and modern distributions block it by default
  (`externally-managed-environment`). Do not work around it with `--break-system-packages`.
- **Windows**: avoids version conflicts between projects and a polluted global Python.
- Keeps PyQt6 and Pillow versions isolated and reproducible, and makes packaging
  (PyInstaller, AppImage) cleaner because only the app's dependencies are present.

Setup:

```text
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

Rules:

- Dependencies are declared in `pyproject.toml` (runtime: `PyQt6`, `Pillow`, `platformdirs`;
  dev extras: `pytest`, and so on). The venv is rebuilt from it at any time.
- Add `.venv/` to `.gitignore`. Never commit the venv.
- Run tests and the app from the activated venv (or call `.venv/bin/python` directly).
- The venv only isolates **Python** packages. FFmpeg and LibreOffice are system-level
  programs installed normally (apt/dnf, or the Windows installer) and found by
  `external_tools.py`. They are not installed with `pip` and are not part of the venv.
- Document these steps in `README.md`.

---

## 15. Services and utilities

- **`settings.py`**: JSON config in the user directory (output directory, conflict mode,
  `max_workers`, recursive import, tool paths).
- **`logging_setup.py`**: rotating log file from day one; captured FFmpeg/LibreOffice
  stdout/stderr.
- **`file_utils.py`**: sizes, output path generation, duplicate naming, atomic write helper.
- **`process_utils.py`**: start subprocess, capture output, parse progress, terminate
  (process trees), timeouts, Windows flags.
- **`format_utils.py`**: human-readable sizes, labels.

---

## 16. Main UI layout

```text
┌──────────────────────────────────────────────────────────────┐
│ FileForge                                  Settings  About  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                  DROP FILES HERE                             │
│                                                              │
│                    + Add files                               │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Queue                                                        │
│                                                              │
│ photo.png       PNG  → JPG     2.4 MB    ████████  ✓        │
│ icon.png        PNG  → ICO     812 KB    █████░░░  ...       │
│ report.docx     DOCX → PDF     1.2 MB    Waiting             │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Output: ~/Downloads/Converted                    [Change]    │
│                                                              │
│ [ Clear ]                                   [ Convert All ]  │
└──────────────────────────────────────────────────────────────┘
```

---

## 17. Roadmap

### v0.1 — Image converter (first stable milestone)

Goal: **`PNG → JPG`, `PNG → WEBP`, `PNG → ICO`, `JPG → PNG` work, in batches, can be
cancelled, and never leave a corrupt output file.**

- Skeleton, logging
- `BaseConverter`, `ConversionContext`, `ConversionJob`, `FormatRegistry`, `ConverterManager`
- `FakeConverter` + `JobManager` + tests (queue, cancel, failure, concurrency)
- `QThreadPool` workers
- Preflight (output path, engine selection, validation, conflicts)
- `ImageConverter` with alpha / EXIF / ICO handling and atomic writes
- Main window, queue model/view, drag & drop, add files
- File detection (extension + Pillow verification)
- Output directory, progress, cancel, per-job errors
- Minimal settings (output directory, conflict mode, worker count)

Not in v0.1: history, options dialog, profiles, audio, video, documents.

### v0.2 — Documents (LibreOffice)

Detection, `document_libreoffice.py`, `BLOCKED` messages, External Tools settings with
manual path and Re-detect.

### v0.3 — Audio

FFmpeg detection, audio formats, FFmpeg progress parsing.

### v0.4 — Video

Video formats, cancelable FFmpeg process, resolution/codec/bitrate options.

### v0.5 — UX

`options_schema()` + `convert_dialog.py`, image preview, better error messages, system
theme, keyboard shortcuts.

### v1.0 — Stable release

Stable architecture, reliable queue, robust cancellation, engine detection, comprehensive
tests, packaging for Linux and Windows.

### Later, only on real demand

Not planned, not stubbed. Add only when a concrete need appears.

- **History** (`history.py`, JSON).
- **Profiles** and **Quick Convert**.
- **Microsoft Word engine** (`document_msoffice.py`, Windows only, COM). The structure
  allows it as a second engine for `docx → pdf`. Expect: single instance, 1 worker, per-job
  timeout, popups that can hang COM, killing only the Word process the app started.
  Write it directly with COM; the `msoffice2pdf` package is not suitable (still needs
  Office or LibreOffice, no cancel/timeout).
- **Pure-Python document engine** (`document_basic.py`), if ever.

---

## 18. Architectural rules

1. **UI does not perform conversion.** `MainWindow → JobManager → ConverterManager → Converter`.
2. **No format-specific `if` chains in UI classes.** Use `FormatRegistry` and `ConverterManager`.
3. **External tools are optional.** Detected at runtime; a missing tool disables only its pairs.
4. **Never block the GUI thread.** Large images, subprocesses, batches, folder scanning: workers.
5. **A failed job must not kill the queue.** Each job ends COMPLETED, FAILED, CANCELLED or BLOCKED.
6. **Converters are independent.** New format or engine = new converter, not edits to
   `main_window.py` or `job_manager.py`.
7. **One converter interface**, in `converters/base.py`.
8. **Converters receive a `ConversionContext`**, never a job.
9. **Policy lives in preflight.** Output paths, conflicts and validation are settled before a
   job is queued; workers only execute.
10. **Jobs are data.** No converter objects, threads or processes inside a job.
11. **Outputs are written atomically.** Temp file, then rename.
12. **Capability vs metadata.** `supported_pairs()` is converter capability; `FORMAT_INFO` is
    format metadata. Do not mix them.

---

## 19. Recommended implementation order

```text
1.  Skeleton + logging
2.  BaseConverter, ConversionContext, ConversionJob / JobStatus
3.  FormatRegistry + ConverterManager
4.  FakeConverter + JobManager + Worker (QThreadPool) + tests
5.  Preflight + tests
6.  ImageConverter (PNG/JPG/WEBP/ICO; alpha, EXIF, atomic write)
7.  Main window + queue model/view + drag & drop
8.  File detection
9.  Minimal settings, error display
10. External tool detection
11. LibreOffice converter (v0.2)
12. FFmpeg converters (v0.3, v0.4)
```

Queue, cancel and error behavior are tested against `FakeConverter` before any real engine
exists. If this pipeline is clean, FFmpeg and LibreOffice are just engines plugged in, and
`main_window.py` never needs to know what FFmpeg is.
