"""MainWindow — layout and wiring.

Forwards user actions to JobManager. Contains no conversion logic and no
format-specific branching: targets come from the FormatRegistry, engine selection
from the ConverterManager.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.converter_manager import ConverterManager
from app.core.file_detector import FileDetector
from app.core.format_registry import FormatRegistry
from app.core.job_manager import JobManager
from app.core.preflight import ConflictDecision
from app.models.conversion_job import ConversionJob, JobStatus
from app.services.external_tools import ExternalTools
from app.services.settings import OutputMode, Settings
from app.ui.dialogs.about_dialog import AboutDialog
from app.ui.dialogs.convert_dialog import ConvertOptionsDialog
from app.ui.drop_area import DropArea, FolderScanWorker
from app.ui.preview import PreviewPanel
from app.ui.queues.queue_delegate import QueueDelegate
from app.ui.queues.queue_model import QueueModel
from app.ui.queues.queue_view import QueueView
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(
        self,
        job_manager: JobManager,
        registry: FormatRegistry,
        settings: Settings,
        external_tools: ExternalTools,
    ) -> None:
        super().__init__()
        self.manager = job_manager
        self.registry = registry
        self.settings = settings
        self.external_tools = external_tools
        self.detector = FileDetector()

        self._scan_workers: set[FolderScanWorker] = set()
        self._ask_all_decision: ConflictDecision | None = None

        self.setWindowTitle("FileForge")
        self.resize(880, 620)

        self._build_menu()
        self._build_ui()
        self._connect_manager()
        self._update_buttons()
        self.statusBar().showMessage("Ready")

    # --------------------------------------------------------------------- layout
    def _build_menu(self) -> None:
        self.add_files_action = QAction("Add Files", self)
        self.add_files_action.setShortcut(QKeySequence.StandardKey.Open)  # Ctrl+O
        self.add_files_action.triggered.connect(self._add_files)

        self.convert_action = QAction("Convert All", self)
        self.convert_action.setShortcuts(
            [QKeySequence("F5"), QKeySequence("Ctrl+R")]
        )
        self.convert_action.triggered.connect(self._convert_all)

        self.clear_action = QAction("Clear queue", self)
        self.clear_action.setShortcut(QKeySequence("Ctrl+L"))
        self.clear_action.triggered.connect(self.manager.clear)

        settings_action = QAction("Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)

        about_action = QAction("About", self)
        about_action.setShortcut(QKeySequence("F1"))
        about_action.triggered.connect(self._open_about)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)

        menu = self.menuBar().addMenu("Menu")
        menu.addAction(self.add_files_action)
        menu.addAction(self.convert_action)
        menu.addAction(self.clear_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addAction(about_action)
        menu.addSeparator()
        menu.addAction(quit_action)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self.drop_area = DropArea(self._name_filter())
        self.drop_area.paths_dropped.connect(self._on_paths_dropped)
        layout.addWidget(self.drop_area)

        queue_label = QLabel("Queue")
        font = queue_label.font()
        font.setBold(True)
        queue_label.setFont(font)
        layout.addWidget(queue_label)

        self.model = QueueModel(self.manager, self)
        self.delegate = QueueDelegate(self.registry, self.manager.set_target_format, self)
        self.view = QueueView(self.model, self.delegate, self)
        self.view.options_requested.connect(self._edit_options)
        self.view.error_requested.connect(self._show_error)
        self.view.cancel_requested.connect(self.manager.cancel_job)
        self.view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        content = QHBoxLayout()
        content.addWidget(self.view, stretch=1)
        self.preview = PreviewPanel(self.registry, self)
        self.preview.setFixedWidth(260)
        content.addWidget(self.preview)
        layout.addLayout(content, stretch=1)

        output_row = QHBoxLayout()
        self.output_label = QLabel()
        self.output_label.setObjectName("mutedText")
        change_button = QPushButton("Change…")
        change_button.clicked.connect(self._change_output)
        output_row.addWidget(self.output_label)
        output_row.addStretch(1)
        output_row.addWidget(change_button)
        layout.addLayout(output_row)

        action_row = QHBoxLayout()
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.manager.clear)
        self.convert_button = QPushButton("Convert All")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(self._convert_all)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)
        action_row.addWidget(self.convert_button)
        layout.addLayout(action_row)

        self._refresh_output_label()

    def _name_filter(self) -> str:
        patterns: list[str] = []
        for fmt in self.registry.known_formats():
            patterns.extend(f"*{ext}" for ext in self.registry.extensions(fmt))
        if not patterns:
            return "All files (*)"
        return f"Supported files ({' '.join(patterns)});;All files (*)"

    # -------------------------------------------------------------------- wiring
    def _connect_manager(self) -> None:
        for signal in (
            self.manager.jobs_added,
            self.manager.job_updated,
            self.manager.job_removed,
            self.manager.queue_cleared,
        ):
            signal.connect(lambda *_: self._update_buttons())
        self.manager.batch_started.connect(self._on_batch_started)
        self.manager.batch_finished.connect(self._on_batch_finished)

    # --------------------------------------------------------------- import flow
    def _on_paths_dropped(self, paths: list[Path]) -> None:
        files: list[Path] = []
        folders: list[Path] = []
        for path in paths:
            (folders if path.is_dir() else files).append(path)
        if files:
            self._import_files(files)
        for folder in folders:
            self._scan_folder(folder)

    def _scan_folder(self, folder: Path) -> None:
        worker = FolderScanWorker(folder, self.settings.recursive_import)
        self._scan_workers.add(worker)
        worker.signals.done.connect(lambda files, w=worker: self._on_scan_done(files, w))
        worker.signals.failed.connect(lambda msg, w=worker: self._on_scan_failed(msg, w))
        QThreadPool.globalInstance().start(worker)

    def _on_scan_done(self, files: list[Path], worker: FolderScanWorker) -> None:
        self._scan_workers.discard(worker)
        self._import_files(files)

    def _on_scan_failed(self, message: str, worker: FolderScanWorker) -> None:
        self._scan_workers.discard(worker)
        QMessageBox.warning(self, "Folder scan failed", message)

    def _import_files(self, files: list[Path]) -> None:
        queued = {job.source for job in self.manager.jobs}
        new_jobs: list[ConversionJob] = []
        blocked = 0

        for path in files:
            if path in queued:
                continue
            info = self.detector.detect(path)
            targets = self.registry.targets_for(info.format)
            if not targets:
                job = ConversionJob(
                    source=path, source_format=info.format, target_format=""
                )
                job.status = JobStatus.BLOCKED
                name = self.registry.display_name(info.format)
                job.error = f"No conversion is available for {name} files."
                new_jobs.append(job)
                blocked += 1
                continue
            target = self._default_target(info.format, targets)
            new_jobs.append(
                ConversionJob(
                    source=path, source_format=info.format, target_format=target
                )
            )

        self.manager.add_jobs(new_jobs)
        if blocked:
            self.statusBar().showMessage(
                f"Imported {len(new_jobs) - blocked} file(s); {blocked} blocked."
            )
        else:
            self.statusBar().showMessage(f"Imported {len(new_jobs)} file(s).")

    def _default_target(self, source_format: str, targets: list[str]) -> str:
        # Video targets come before audio so a video source defaults to a video output
        # (audio extraction is available in the menu, just not the default).
        for preferred in ("jpg", "png", "pdf", "mp4", "webm", "mkv", "mp3"):
            if preferred in targets and preferred != source_format:
                return preferred
        return targets[0]

    # ------------------------------------------------------------------ actions
    def _add_files(self) -> None:
        self.drop_area.browse()

    def _on_selection_changed(self, *_args) -> None:
        indexes = self.view.selectedIndexes()
        job = self.model.job_at(indexes[0]) if indexes else None
        self.preview.show_job(job)

    def _edit_options(self, job: ConversionJob) -> None:
        converter = self.registry.get(job.selected_engine) if job.selected_engine else None
        if converter is None:
            engines = self.registry.engines_for(job.source_format, job.target_format)
            converter = engines[0] if engines else None
        if converter is None:
            QMessageBox.information(
                self, "Options", "No engine is available for this conversion."
            )
            return
        schema = converter.options_schema(job.source_format, job.target_format)
        if not schema:
            QMessageBox.information(self, "Options", "This conversion has no options.")
            return
        dialog = ConvertOptionsDialog(schema, job.options, parent=self)
        if dialog.exec():
            self.manager.set_options(job, dialog.values())

    def _show_error(self, job: ConversionJob) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Conversion error")
        box.setText(job.filename)
        box.setInformativeText(job.error or "No details are available.")
        box.exec()

    def _convert_all(self) -> None:
        self._ask_all_decision = None
        result = self.manager.start_all(ask=self._ask_conflict)
        if result.rejected:
            self.statusBar().showMessage(
                f"{len(result.rejected)} job(s) blocked; {len(result.ready)} queued."
            )
        self._update_buttons()

    def _change_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose output folder",
            self.settings.output_directory or str(Path.home()),
        )
        if chosen:
            self.settings.output_mode = OutputMode.CUSTOM_FOLDER.value
            self.settings.output_directory = chosen
            self.settings.save()
            self._refresh_output_label()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.external_tools, self)
        if dialog.exec():
            self._refresh_output_label()
            app = QApplication.instance()
            if app is not None:
                apply_theme(app, self.settings.theme)

    def _open_about(self) -> None:
        AboutDialog(self).exec()

    def closeEvent(self, event) -> None:  # noqa: N802
        # Quitting while jobs run used to exit silently, leaving FFmpeg/LibreOffice
        # subprocesses and temp files behind. Confirm first, then cancel cleanly.
        if self.manager.is_running():
            reply = QMessageBox.question(
                self,
                "Quit while converting?",
                "Conversions are still running.\nQuitting will cancel them.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.manager.cancel_all()
            self.manager.wait_for_done(3000)
        event.accept()

    # ------------------------------------------------------------------ conflict
    def _ask_conflict(self, job: ConversionJob, path: Path) -> ConflictDecision:
        if self._ask_all_decision is not None:
            return self._ask_all_decision

        box = QMessageBox(self)
        box.setWindowTitle("File already exists")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"“{path.name}” already exists in the output folder.")
        box.setInformativeText("What should FileForge do?")
        overwrite = box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Skip", QMessageBox.ButtonRole.DestructiveRole)
        rename = box.addButton("Rename", QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(rename)
        apply_all = QCheckBox("Apply to all remaining conflicts")
        box.setCheckBox(apply_all)
        box.exec()

        clicked = box.clickedButton()
        if clicked is overwrite:
            decision = ConflictDecision.OVERWRITE
        elif clicked is skip:
            decision = ConflictDecision.SKIP
        else:
            decision = ConflictDecision.RENAME
        if apply_all.isChecked():
            self._ask_all_decision = decision
        return decision

    # ------------------------------------------------------------------- helpers
    def _output_summary(self) -> str:
        mode = self.settings.output_mode
        if mode == OutputMode.SAME_FOLDER.value:
            return "Output: same folder as source"
        if mode == OutputMode.CUSTOM_SUBFOLDER.value:
            return f"Output: “{self.settings.output_subfolder}” next to source"
        return f"Output: {self.settings.output_directory}"

    def _refresh_output_label(self) -> None:
        self.output_label.setText(self._output_summary())

    def _update_buttons(self) -> None:
        running = self.manager.is_running()
        has_jobs = bool(self.manager.jobs)
        convert_enabled = has_jobs and not running
        clear_enabled = not running and has_jobs
        self.convert_button.setEnabled(convert_enabled)
        self.clear_button.setEnabled(clear_enabled)
        # Keep the keyboard shortcuts consistent with the buttons, otherwise Ctrl+L
        # could still clear (and cancel) the queue while the button is disabled.
        self.convert_action.setEnabled(convert_enabled)
        self.clear_action.setEnabled(clear_enabled)

    def _on_batch_started(self) -> None:
        self._update_buttons()
        self.statusBar().showMessage("Converting…")

    def _on_batch_finished(self) -> None:
        self._update_buttons()
        jobs = self.manager.jobs
        completed = sum(1 for j in jobs if j.status is JobStatus.COMPLETED)
        failed = sum(1 for j in jobs if j.status is JobStatus.FAILED)
        blocked = sum(1 for j in jobs if j.status is JobStatus.BLOCKED)
        parts = [f"{completed} done"]
        if failed:
            parts.append(f"{failed} failed")
        if blocked:
            parts.append(f"{blocked} blocked")
        self.statusBar().showMessage("Finished — " + ", ".join(parts))
