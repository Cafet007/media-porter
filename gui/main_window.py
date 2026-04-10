"""
Main Window — top-level application window.

Layout:
  ┌──────────────────────────────────────────────────────────────┐
  │  Toolbar: title · status · [Files][History] · [◐] [Settings]│
  ├──────────────┬──────────────────────────────┬───────────────┤
  │ Source Panel │  FileTable / HistoryPanel     │  Dest Panel   │
  │  (sidebar)   │     (stacked, stretches)      │  (right col)  │
  ├──────────────┴──────────────────────────────┴───────────────┤
  │  [Scan Card]   ████ progress ████   [Import New Files →]     │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import threading
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QSplitter,
    QStatusBar, QMessageBox, QStackedWidget, QButtonGroup,
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont
from gui.widgets.source_panel import ElidedLabel

from backend.utils.detector import DriveInfo
from backend.utils.config import (
    get_dest_paths, save_dest_paths, get_rules,
    get_dark_mode, save_dark_mode,
)
from backend.core.scanner import scan_card
from backend.core.inspector import inspect_all
from backend.core.dedup import DedupChecker
from backend.core.importer import run_import
from backend.core.rules import DestinationConfig
from backend.core.safety import check_batch_space, protect

from gui.theme import T
from .widgets.source_panel import SourcePanel
from .widgets.dest_panel import DestPanel
from .widgets.file_table import FileTable
from .widgets.history_panel import HistoryPanel

logger = logging.getLogger(__name__)


class _Signals(QObject):
    scan_done   = Signal(object, object)
    progress    = Signal(int, int, str, float, float, float, float)
    verify_done = Signal(str, bool)
    import_done = Signal(object)
    status      = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Porter")
        self.setMinimumSize(960, 660)

        self._sig = _Signals()
        self._sig.scan_done.connect(self._on_scan_done)
        self._sig.progress.connect(self._on_progress)
        self._sig.verify_done.connect(self._on_verify_done)
        self._sig.import_done.connect(self._on_import_done)
        self._sig.status.connect(self._set_status)

        self._scan_result = None
        self._new_set: set[tuple[str, int]] = set()
        self._dest_config: DestinationConfig | None = None
        self._cancel_event = threading.Event()
        self._current_file: str | None = None
        self._importing = False
        self._last_import_result = None

        T.set_dark(get_dark_mode())
        self._build_ui()
        self._apply_theme()
        self._load_saved_config()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        # ── three-column body ──────────────────────────────────────────
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(1)

        self._source_panel = SourcePanel()
        self._source_panel.drive_selected.connect(self._on_drive_selected)
        self._splitter.addWidget(self._source_panel)

        # Center: stacked file table / history
        self._stack = QStackedWidget()
        self._file_table = FileTable()
        self._history_panel = HistoryPanel()
        self._stack.addWidget(self._file_table)
        self._stack.addWidget(self._history_panel)
        self._splitter.addWidget(self._stack)

        self._dest_panel = DestPanel()
        self._dest_panel.config_changed.connect(self._on_config_changed)
        self._splitter.addWidget(self._dest_panel)

        self._splitter.setSizes([240, 620, 260])
        root.addWidget(self._splitter, stretch=1)

        root.addWidget(self._build_action_bar())

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)
        self._set_status("Ready — plug in your SD card")

    def _build_toolbar(self) -> QWidget:
        self._toolbar = QWidget()
        self._toolbar.setObjectName("mainToolbar")
        self._toolbar.setFixedHeight(56)
        layout = QHBoxLayout(self._toolbar)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(10)

        # App title
        self._app_title = QLabel("Media Porter")
        f = QFont()
        f.setPixelSize(17)
        f.setBold(True)
        self._app_title.setFont(f)
        layout.addWidget(self._app_title)

        layout.addSpacing(8)

        # Status
        self._header_status = ElidedLabel("")
        self._header_status.setFont(QFont("Arial", 12))
        self._header_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._header_status, stretch=1)

        # Segmented tab control
        self._seg_container = QWidget()
        self._seg_container.setObjectName("segContainer")
        self._seg_container.setFixedHeight(36)
        seg_layout = QHBoxLayout(self._seg_container)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(1)

        self._files_btn = QPushButton("Files")
        self._files_btn.setCheckable(True)
        self._files_btn.setChecked(True)
        self._files_btn.setFixedHeight(30)
        self._files_btn.clicked.connect(lambda: self._switch_view(0))

        self._history_btn = QPushButton("History")
        self._history_btn.setCheckable(True)
        self._history_btn.setFixedHeight(30)
        self._history_btn.clicked.connect(lambda: self._switch_view(1))

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_group.addButton(self._files_btn, 0)
        self._tab_group.addButton(self._history_btn, 1)

        seg_layout.addWidget(self._files_btn)
        seg_layout.addWidget(self._history_btn)
        layout.addWidget(self._seg_container)

        layout.addSpacing(6)

        # Theme toggle + Settings
        self._theme_btn = QPushButton()
        self._theme_btn.setFixedSize(68, 32)
        self._theme_btn.setToolTip("Toggle dark / light mode")
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn)

        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setFixedHeight(32)
        self._settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(self._settings_btn)

        return self._toolbar

    def _build_action_bar(self) -> QWidget:
        self._action_bar = QWidget()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setFixedHeight(68)
        layout = QHBoxLayout(self._action_bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(14)

        self._scan_btn = QPushButton("Scan Card")
        self._scan_btn.setFixedHeight(38)
        self._scan_btn.setFixedWidth(120)
        self._scan_btn.setEnabled(False)
        self._scan_btn.clicked.connect(self._do_scan)
        layout.addWidget(self._scan_btn)

        progress_col = QWidget()
        pcol_layout = QVBoxLayout(progress_col)
        pcol_layout.setContentsMargins(0, 0, 0, 0)
        pcol_layout.setSpacing(6)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        pcol_layout.addWidget(self._progress)

        self._file_progress = QProgressBar()
        self._file_progress.setRange(0, 1000)
        self._file_progress.setValue(0)
        self._file_progress.setFixedHeight(3)
        self._file_progress.setTextVisible(False)
        self._file_progress.setVisible(False)
        pcol_layout.addWidget(self._file_progress)

        layout.addWidget(progress_col, stretch=1)

        self._import_btn = QPushButton("Import New Files →")
        self._import_btn.setFixedHeight(38)
        self._import_btn.setFixedWidth(196)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._do_import)
        layout.addWidget(self._import_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(38)
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._do_cancel)
        layout.addWidget(self._cancel_btn)

        self._report_btn = QPushButton("Save Report")
        self._report_btn.setFixedHeight(38)
        self._report_btn.setFixedWidth(120)
        self._report_btn.setVisible(False)
        self._report_btn.clicked.connect(self._do_save_report)
        layout.addWidget(self._report_btn)

        return self._action_bar

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _toggle_theme(self):
        T.set_dark(not T.dark)
        save_dark_mode(T.dark)
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(
            f"QMainWindow {{ background: {T.BG_BASE}; }}"
            f" QLabel {{ background: transparent; }}"
        )

        # Toolbar
        self._toolbar.setStyleSheet(T.TOOLBAR_STYLE)
        self._app_title.setStyleSheet(f"color: {T.TEXT_PRIMARY};")
        self._header_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px;")
        self._seg_container.setStyleSheet(T.SEGMENT_STYLE)
        self._theme_btn.setText("Light" if T.dark else "Dark")
        self._theme_btn.setStyleSheet(T.btn_secondary(h=32))
        self._settings_btn.setStyleSheet(T.btn_secondary(h=32))

        # Splitter
        self._splitter.setStyleSheet(
            f"QSplitter {{ background: {T.BG_BASE}; }}"
            f" QSplitter::handle {{ background: {T.SPLITTER}; }}"
        )

        # Action bar
        self._action_bar.setStyleSheet(T.ACTIONBAR_STYLE)
        self._scan_btn.setStyleSheet(T.btn_secondary(h=38))
        self._import_btn.setStyleSheet(T.btn_primary(h=38))
        self._cancel_btn.setStyleSheet(T.btn_danger(h=38))
        self._report_btn.setStyleSheet(T.btn_secondary(h=38))
        self._progress.setStyleSheet(T.PROGRESS_STYLE)
        self._file_progress.setStyleSheet(T.FILE_PROGRESS_STYLE)

        # Status bar
        self._status_bar.setStyleSheet(
            f"QStatusBar {{ background: {T.BG_BOTTOM}; color: {T.TEXT_SECONDARY};"
            f" font-size: 12px; border-top: 1px solid {T.DIVIDER}; padding: 0 8px; }}"
            f" QStatusBar::item {{ border: none; }}"
        )

        # Child panels
        self._source_panel.apply_theme()
        self._dest_panel.apply_theme()
        self._file_table.apply_theme()
        self._history_panel.apply_theme()

    # ------------------------------------------------------------------
    # View switching
    # ------------------------------------------------------------------

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        if index == 1:
            self._history_panel.load()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _open_settings(self):
        from .widgets.settings_panel import SettingsDialog
        dlg = SettingsDialog(get_rules(), parent=self)
        dlg.rules_saved.connect(self._on_rules_saved)
        dlg.exec()

    def _on_rules_saved(self, rules: dict):
        if self._dest_config:
            self._dest_config.templates = rules
        logger.info("Rules updated: %s", rules)

    def _on_drive_selected(self, drive: DriveInfo):
        logger.info("Drive selected: %s (%s)", drive.label, drive.mount_point)
        self._header_status.setText(f"{drive.label}  ·  {drive.total_gb} GB")

        if drive.is_camera_card:
            self._selected_drive = drive
            protect(drive.mount_point)
            self._scan_btn.setEnabled(True)
            self._set_status(f"Camera card: {drive.label}  —  click Scan to continue")
        elif drive.is_external_drive:
            self._dest_panel.set_drive_root(drive.mount_point)
            self._set_status(f"Destination set to {drive.label} ({drive.mount_point})")

    def _load_saved_config(self):
        paths = get_dest_paths()
        if paths:
            photo, video = paths
            self._dest_panel.set_paths(photo, video)
            logger.info("Restored dest config from saved config")

    def _on_config_changed(self, config: DestinationConfig):
        config.templates = get_rules()
        self._dest_config = config
        save_dest_paths(config.photo_base, config.video_base)

        if not self._importing and self._scan_result and self._new_set:
            new_count = len(self._new_set)
            self._import_btn.setEnabled(new_count > 0)
            self._import_btn.setText(
                f"Import {new_count} New Files →" if new_count else "Nothing to Import"
            )

    def _do_scan(self):
        if not hasattr(self, "_selected_drive"):
            return
        drive = self._selected_drive

        if self._dest_config and self._is_dest_drive(drive):
            self._set_status("Cannot scan destination drive — select your SD card instead.")
            return

        self._scan_btn.setEnabled(False)
        self._import_btn.setEnabled(False)
        self._report_btn.setVisible(False)
        self._last_import_result = None
        self._file_table.clear()
        self._progress.setValue(0)
        self._set_status("Scanning SD card…")
        self._switch_view(0)
        self._files_btn.setChecked(True)
        logger.info("Scan started: %s", drive.mount_point)
        config = self._dest_config

        def _worker():
            try:
                result = scan_card(drive.mount_point)
                infos = inspect_all([f.path for f in result.files])
                info_map = {i.path: i for i in infos}
                for f in result.files:
                    info = info_map.get(f.path)
                    if info and info.captured_at:
                        f.captured_at = info.captured_at

                new_set: set[tuple[str, int]] = set()
                if config:
                    from backend.core.models import MediaType
                    checker_p = DedupChecker(config.photo_base)
                    checker_v = DedupChecker(config.video_base)
                    checker_p.build_index()
                    checker_v.build_index()
                    for f in result.files:
                        checker = checker_v if f.media_type == MediaType.VIDEO else checker_p
                        if not checker.exists(f):
                            new_set.add((f.name, f.size_bytes))
                else:
                    new_set = {(f.name, f.size_bytes) for f in result.files}

                self._sig.scan_done.emit(result, new_set)
            except Exception as e:
                logger.error("Scan failed: %s", e)
                self._sig.status.emit(f"Scan failed: {e}")
                self._sig.scan_done.emit(None, set())

        threading.Thread(target=_worker, daemon=True).start()

    def _on_scan_done(self, result, new_set: set[str]):
        self._scan_result = result
        self._new_set = new_set
        self._scan_btn.setEnabled(True)

        if result is None:
            return

        self._file_table.load(result.files, new_set)
        profile_name = result.profile.name if result.profile else "Unknown"
        self._file_table.set_scan_info(profile_name, result.roots_scanned)
        new_count = len(new_set)
        already_count = result.total - new_count
        logger.info("Scan done: %d total, %d new", result.total, new_count)
        self._import_btn.setEnabled(new_count > 0 and self._dest_config is not None)
        self._import_btn.setText(f"Import {new_count} New Files →" if new_count else "Nothing to Import")

        if already_count > 0 and new_count > 0:
            self._set_status(
                f"Resuming — {already_count} already imported  ·  {new_count} new to import"
            )
        elif already_count > 0 and new_count == 0:
            self._set_status(
                f"All {result.total} files already imported — nothing to do"
            )
        else:
            self._set_status(
                f"Scanned: {result.total} files  ·  {new_count} new"
            )

    def _do_import(self):
        if not self._scan_result or not self._dest_config:
            return

        new_files = [f for f in self._scan_result.files if (f.name, f.size_bytes) in self._new_set]
        config = self._dest_config

        errors = check_batch_space(new_files, config)
        if errors:
            total_needed = sum(f.size_bytes for f in new_files) / 1_073_741_824
            msg = QMessageBox(self)
            msg.setWindowTitle("Not Enough Space")
            msg.setIcon(QMessageBox.Critical)
            msg.setText(f"Not enough space to import {len(new_files)} files ({total_needed:.2f} GB total).")
            msg.setInformativeText("\n".join(errors))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            return

        self._importing = True
        self._import_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._cancel_event.clear()
        self._progress.setValue(0)
        self._file_progress.setValue(0)
        self._file_progress.setVisible(True)
        self._set_status("Importing…")
        logger.info("Import started: %d new files", len(new_files))

        files = self._scan_result.files

        def _worker():
            def on_progress(done, total, name, bytes_done, bytes_total, file_bytes_done, file_bytes_total):
                self._sig.progress.emit(done, total, name, bytes_done, bytes_total, file_bytes_done, file_bytes_total)
            def on_verify(name, ok):
                self._sig.verify_done.emit(name, ok)
            result = run_import(files, config, progress_cb=on_progress,
                                verify_cb=on_verify, cancel_event=self._cancel_event)
            self._sig.import_done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, done: int, total: int, filename: str, bytes_done: float, bytes_total: float, file_bytes_done: float, file_bytes_total: float):
        overall = bytes_done / bytes_total if bytes_total else 1.0
        self._progress.setValue(int(overall * 100))

        file_progress = file_bytes_done / file_bytes_total if file_bytes_total else 1.0
        self._file_progress.setValue(int(file_progress * 1000))

        mb_done  = bytes_done  / 1_048_576
        mb_total = bytes_total / 1_048_576
        self._set_status(f"Copying  {done}/{total}  —  {filename}  ({mb_done:.0f} / {mb_total:.0f} MB)")

        if filename != self._current_file:
            self._current_file = filename
            self._file_table.mark_in_progress(filename)
        if file_bytes_done >= file_bytes_total and file_bytes_total > 0:
            self._current_file = None
            self._file_table.mark_verifying(filename)

    def _on_verify_done(self, filename: str, ok: bool):
        if ok:
            self._file_table.mark_verified(filename)
        else:
            self._file_table.mark_verify_failed(filename)

    def _do_cancel(self):
        self._cancel_event.set()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelling…")
        self._set_status("Cancelling — finishing current file…")

    def _on_import_done(self, result):
        cancelled = self._cancel_event.is_set()
        logger.info("Import done: %s%s", result.summary(), " (cancelled)" if cancelled else "")
        self._progress.setValue(100 if not cancelled else self._progress.value())
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("Cancel")

        self._importing = False
        self._last_import_result = result
        self._file_progress.setVisible(False)
        self._file_progress.setValue(0)

        for f in result.conflicts:
            self._file_table.mark_conflict(f.name)
        for f, _ in result.failed:
            self._file_table.mark_failed(f.name)

        if cancelled:
            self._set_status(f"Cancelled — {result.summary()}")
            self._import_btn.setText("Import Cancelled")
        elif result.total_verify_failed:
            self._set_status(
                f"{result.summary()}  ·  ⚠ {result.total_verify_failed} file(s) failed verification"
            )
            self._import_btn.setText("Import Complete — Verify Errors ⚠")
        else:
            self._set_status(result.summary())
            self._import_btn.setText("Import Complete ✓")
        self._import_btn.setEnabled(False)
        self._report_btn.setVisible(True)

    def _do_save_report(self):
        if not self._last_import_result:
            return
        from backend.core.report import write_report
        from datetime import datetime

        default_dir = str(self._dest_config.photo_base.parent) if self._dest_config else str(Path.home())
        default_name = f"media-porter-report_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.csv"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Import Report",
            str(Path(default_dir) / default_name),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        dest_path = Path(path)
        try:
            written = write_report(self._last_import_result, dest_path.parent,
                                   session_name=dest_path.stem)
            self._set_status(f"Report saved: {written}")
        except Exception as e:
            QMessageBox.critical(self, "Save Report Failed", str(e))

    def _is_dest_drive(self, drive: DriveInfo) -> bool:
        mount = drive.mount_point
        for path in (self._dest_config.photo_base, self._dest_config.video_base):
            try:
                path.relative_to(mount)
                return True
            except ValueError:
                pass
        return False

    def _set_status(self, msg: str):
        self._status_bar.showMessage(msg)
