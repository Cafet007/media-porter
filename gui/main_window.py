"""
Main Window — top-level application window.

Layout:
  ┌──────────────────────────────────────────────────────┐
  │  Header bar (app name + status)                      │
  ├──────────────┬───────────────────────┬───────────────┤
  │ Source Panel │    File Table         │  Dest Panel   │
  │ (drives)     │    (file list)        │  (paths)      │
  ├──────────────┴───────────────────────┴───────────────┤
  │  [SCAN]   Progress bar   [IMPORT NEW FILES]          │
  └──────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import threading
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QSplitter, QStatusBar, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QObject, QMetaObject, Q_ARG
from PySide6.QtGui import QFont

from backend.utils.detector import DriveInfo
from backend.utils.config import get_dest_paths, save_dest_paths
from backend.core.scanner import scan_card
from backend.core.inspector import inspect_all
from backend.core.dedup import DedupChecker
from backend.core.importer import run_import
from backend.core.rules import DestinationConfig
from backend.core.safety import check_batch_space

from .widgets.source_panel import SourcePanel
from .widgets.dest_panel import DestPanel
from .widgets.file_table import FileTable

logger = logging.getLogger(__name__)


class _Signals(QObject):
    scan_done    = Signal(object, object)        # (ScanResult, new_set)
    progress     = Signal(int, int, str, float, float)  # (done, total, filename, bytes_done, bytes_total)
    import_done  = Signal(object)                # ImportResult
    status       = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Mporter")
        self.setMinimumSize(1100, 680)

        self._sig = _Signals()
        self._sig.scan_done.connect(self._on_scan_done)
        self._sig.progress.connect(self._on_progress)
        self._sig.import_done.connect(self._on_import_done)
        self._sig.status.connect(self._set_status)

        self._scan_result = None
        self._new_set: set[str] = set()
        self._dest_config: DestinationConfig | None = None
        self._cancel_event = threading.Event()
        self._current_file: str | None = None
        self._importing = False

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

        root.addWidget(self._build_header())

        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #333; }")

        self._source_panel = SourcePanel()
        self._source_panel.drive_selected.connect(self._on_drive_selected)
        splitter.addWidget(self._source_panel)

        self._file_table = FileTable()
        splitter.addWidget(self._file_table)

        self._dest_panel = DestPanel()
        self._dest_panel.config_changed.connect(self._on_config_changed)
        splitter.addWidget(self._dest_panel)

        splitter.setSizes([280, 580, 280])
        root.addWidget(splitter, stretch=1)

        root.addWidget(self._build_bottom_bar())

        # Status bar
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet("background: #111; color: #666; font-size: 11px;")
        self.setStatusBar(self._status_bar)
        self._set_status("Ready — plug in your SD card")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background: #111; border-bottom: 1px solid #2a2a2a;")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("Media Mporter")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #eee;")
        layout.addWidget(title)

        layout.addStretch()

        self._header_status = QLabel("")
        self._header_status.setFont(QFont("Arial", 12))
        self._header_status.setStyleSheet("color: #666;")
        layout.addWidget(self._header_status)

        return header

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(76)
        bar.setStyleSheet("background: #111; border-top: 1px solid #2a2a2a;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        # Scan button
        self._scan_btn = QPushButton("⟳  Scan Card")
        self._scan_btn.setFixedHeight(40)
        self._scan_btn.setFixedWidth(130)
        self._scan_btn.setEnabled(False)
        self._scan_btn.clicked.connect(self._do_scan)
        self._scan_btn.setStyleSheet(self._btn_style("#333", "#444"))
        layout.addWidget(self._scan_btn)

        # Stacked progress bars (overall on top, current file below)
        progress_col = QWidget()
        progress_layout = QVBoxLayout(progress_col)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(5)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet("""
            QProgressBar { background: #2a2a2a; border-radius: 4px; border: none; }
            QProgressBar::chunk { background: #4a9eff; border-radius: 4px; }
        """)
        progress_layout.addWidget(self._progress)

        self._file_progress = QProgressBar()
        self._file_progress.setRange(0, 1000)
        self._file_progress.setValue(0)
        self._file_progress.setFixedHeight(5)
        self._file_progress.setTextVisible(False)
        self._file_progress.setVisible(False)
        self._file_progress.setStyleSheet("""
            QProgressBar { background: #1e1e1e; border-radius: 3px; border: none; }
            QProgressBar::chunk { background: #2ecc71; border-radius: 3px; }
        """)
        progress_layout.addWidget(self._file_progress)

        layout.addWidget(progress_col, stretch=1)

        # Import button
        self._import_btn = QPushButton("Import New Files →")
        self._import_btn.setFixedHeight(40)
        self._import_btn.setFixedWidth(180)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._do_import)
        self._import_btn.setStyleSheet(self._btn_style("#4a9eff", "#5aaeff", text_color="white"))
        layout.addWidget(self._import_btn)

        # Cancel button — visible only during import
        self._cancel_btn = QPushButton("✕  Cancel")
        self._cancel_btn.setFixedHeight(40)
        self._cancel_btn.setFixedWidth(110)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._do_cancel)
        self._cancel_btn.setStyleSheet(self._btn_style("#5a1a1a", "#7a2a2a", text_color="#ff6b6b"))
        layout.addWidget(self._cancel_btn)

        return bar

    def _btn_style(self, bg, hover_bg, text_color="#ccc") -> str:
        return f"""
            QPushButton {{
                background: {bg}; border: none; border-radius: 8px;
                color: {text_color}; font-size: 13px; font-weight: bold;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: {hover_bg}; }}
            QPushButton:disabled {{ background: #222; color: #555; }}
        """

    def _apply_theme(self):
        self.setStyleSheet("QMainWindow { background: #1a1a1a; }")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_drive_selected(self, drive: DriveInfo):
        logger.info("Drive selected: %s (%s)", drive.label, drive.mount_point)
        self._header_status.setText(f"{drive.label}  ·  {drive.total_gb} GB")

        if drive.is_camera_card:
            self._selected_drive = drive
            self._scan_btn.setEnabled(True)
            self._set_status(f"Camera card: {drive.label}  —  click Scan to continue")
        elif drive.is_external_drive:
            self._dest_panel.set_drive_root(drive.mount_point)
            self._set_status(f"Destination set to {drive.label} ({drive.mount_point})")

    def _load_saved_config(self):
        """Pre-fill destination paths from last session."""
        paths = get_dest_paths()
        if paths:
            photo, video = paths
            self._dest_panel.set_paths(photo, video)
            logger.info("Restored dest config from saved config")

    def _on_config_changed(self, config: DestinationConfig):
        self._dest_config = config
        save_dest_paths(config.photo_base, config.video_base)
        logger.debug("Dest config updated: photos=%s  videos=%s", config.photo_base, config.video_base)

        # If a scan already ran, re-evaluate the import button now that dest is set
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

        # Block scanning the destination drive
        if self._dest_config and self._is_dest_drive(drive):
            self._set_status("Cannot scan destination drive — select your SD card instead.")
            logger.warning("Scan blocked: %s is the destination drive", drive.mount_point)
            return

        self._scan_btn.setEnabled(False)
        self._import_btn.setEnabled(False)
        self._file_table.clear()
        self._progress.setValue(0)
        self._set_status("Scanning SD card...")
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

                # Dedup check
                new_set: set[str] = set()
                if config:
                    from backend.core.models import MediaType
                    checker_p = DedupChecker(config.photo_base)
                    checker_v = DedupChecker(config.video_base)
                    checker_p.build_index()
                    checker_v.build_index()
                    for f in result.files:
                        checker = checker_v if f.media_type == MediaType.VIDEO else checker_p
                        if not checker.exists(f):
                            new_set.add(f.name)
                else:
                    new_set = {f.name for f in result.files}

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

        new_count = len(new_set)
        logger.info("Scan done: %d total, %d new", result.total, new_count)
        self._import_btn.setEnabled(new_count > 0 and self._dest_config is not None)
        self._import_btn.setText(f"Import {new_count} New Files →" if new_count else "Nothing to Import")
        self._set_status(
            f"Scanned: {result.total} files  ·  "
            f"New: {new_count}  ·  Already imported: {result.total - new_count}"
        )

    def _do_import(self):
        if not self._scan_result or not self._dest_config:
            return

        new_files = [f for f in self._scan_result.files if f.name in self._new_set]
        config = self._dest_config

        # Pre-flight space check across all destination drives
        errors = check_batch_space(new_files, config)
        if errors:
            total_needed = sum(f.size_bytes for f in new_files) / 1_073_741_824
            msg = QMessageBox(self)
            msg.setWindowTitle("Not Enough Space")
            msg.setIcon(QMessageBox.Critical)
            msg.setText(
                f"Not enough space to import {len(new_files)} files "
                f"({total_needed:.2f} GB total)."
            )
            msg.setInformativeText("\n".join(errors))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            logger.warning("Import blocked — insufficient space: %s", errors)
            return

        self._importing = True
        self._import_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._cancel_event.clear()
        self._progress.setValue(0)
        self._file_progress.setValue(0)
        self._file_progress.setVisible(True)
        self._set_status("Importing...")
        logger.info("Import started: %d new files", len(new_files))

        files = self._scan_result.files

        def _worker():
            def on_progress(done, total, name, bytes_done, bytes_total):
                self._sig.progress.emit(done, total, name, bytes_done, bytes_total)

            result = run_import(files, config, progress_cb=on_progress,
                                cancel_event=self._cancel_event)
            self._sig.import_done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, done: int, total: int, filename: str, bytes_done: float, bytes_total: float):
        file_pct = bytes_done / bytes_total if bytes_total else 1.0
        overall  = (done - 1 + file_pct) / total
        self._progress.setValue(int(overall * 100))
        self._file_progress.setValue(int(file_pct * 1000))

        mb_done  = bytes_done  / 1_048_576
        mb_total = bytes_total / 1_048_576
        self._set_status(
            f"Copying  {done}/{total}  —  {filename}  "
            f"({mb_done:.0f} / {mb_total:.0f} MB)"
        )

        # Mark row as in-progress on first chunk, copied when done
        if filename != self._current_file:
            self._current_file = filename
            self._file_table.mark_in_progress(filename)

        if bytes_done == bytes_total:
            self._current_file = None
            self._file_table.mark_copied(filename)

    def _do_cancel(self):
        self._cancel_event.set()
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelling...")
        self._set_status("Cancelling — finishing current file...")
        logger.info("Import cancel requested by user")

    def _on_import_done(self, result):
        cancelled = self._cancel_event.is_set()
        logger.info("Import done: %s%s", result.summary(), " (cancelled)" if cancelled else "")
        self._progress.setValue(100 if not cancelled else self._progress.value())
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("✕  Cancel")

        self._importing = False
        self._file_progress.setVisible(False)
        self._file_progress.setValue(0)

        for f, _ in result.failed:
            self._file_table.mark_failed(f.name)

        if cancelled:
            self._set_status(f"Cancelled — {result.summary()}")
            self._import_btn.setText("Import Cancelled")
        else:
            self._set_status(result.summary())
            self._import_btn.setText("Import Complete ✓")
        self._import_btn.setEnabled(False)

    def _is_dest_drive(self, drive: DriveInfo) -> bool:
        """Return True if the drive contains the configured destination paths."""
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
