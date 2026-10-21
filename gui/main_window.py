"""
Main Window — top-level application window.

Layout:
  ┌──────────────────────────────────────────────────────────────┐
  │  Native menu bar: Import · View · Settings                  │
  │  Toolbar: title · status                                    │
  ├──────────────┬──────────────────────────────┬───────────────┤
  │ Source Panel │  Files / History / Summary    │  Dest Panel   │
  │  (sidebar)   │     (stacked, stretches)      │  (right col)  │
  ├──────────────┴──────────────────────────────┴───────────────┤
  │  [Scan Card]   ████ progress ████   [Import New Files →]     │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QSplitter,
    QStatusBar, QMessageBox, QStackedWidget, QMenu,
    QFileDialog, QDialog, QApplication,
)
from PySide6.QtCore import Qt, Signal, QObject, QUrl
from PySide6.QtGui import QAction, QActionGroup, QFont, QDesktopServices, QGuiApplication, QKeySequence
from gui.widgets.source_panel import ElidedLabel

from backend.utils.detector import DriveInfo, eject
from backend.utils.config import (
    get_dest_paths, save_dest_paths, get_rules,
    get_theme_mode, save_theme_mode, get_auto_scan, save_auto_scan,
)
from backend.utils.notify import notify
from backend.utils.power import KeepAwake
from backend.core.messages import format_duration, format_size
from backend.core.scanner import scan_card
from backend.core.inspector import inspect_all
from backend.core.metadata import extract_all
from backend.core.importer import plan_import, run_import
from backend.core.rules import DestinationConfig
from backend.core.safety import check_batch_space, protect, unprotect

from gui.theme import T, apply_app_palette, system_prefers_dark
from .widgets.source_panel import SourcePanel
from .widgets.dest_panel import DestPanel
from .widgets.file_table import FileTable
from .widgets.history_panel import HistoryPanel
from .widgets.session_dialog import SessionNameDialog
from .widgets.summary_panel import SummaryPanel

logger = logging.getLogger(__name__)


class _Signals(QObject):
    scan_done   = Signal(object, object)
    scan_progress = Signal(str, int, int)      # phase label, done, total
    plan_done   = Signal(object, int)          # new_set, generation
    progress    = Signal(int, int, str, float, float, float, float)
    verify_progress = Signal(str, float, float)
    verify_done = Signal(str, bool)
    import_done = Signal(object)
    eject_done  = Signal(bool, str)
    status      = Signal(str)


_VIEW_FILES, _VIEW_HISTORY, _VIEW_SUMMARY = 0, 1, 2
_SPEED_WINDOW_SEC = 8.0   # copy speed is averaged over this many seconds


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Porter")
        self.setMinimumSize(960, 660)

        self._sig = _Signals()
        self._sig.scan_done.connect(self._on_scan_done)
        self._sig.scan_progress.connect(self._on_scan_progress)
        self._sig.plan_done.connect(self._on_plan_done)
        self._sig.progress.connect(self._on_progress)
        self._sig.verify_progress.connect(self._on_verify_progress)
        self._sig.verify_done.connect(self._on_verify_done)
        self._sig.import_done.connect(self._on_import_done)
        self._sig.eject_done.connect(self._on_eject_done)
        self._sig.status.connect(self._set_status)

        self._scan_result = None
        self._new_set: set[str] = set()
        self._dest_config: DestinationConfig | None = None
        self._cancel_event = threading.Event()
        self._importing = False
        self._scanning = False
        self._scan_config_stale = False
        self._plan_generation = 0
        self._started_files: set[str] = set()
        self._session_name = ""
        self._selected_drive: DriveInfo | None = None
        self._keep_awake = KeepAwake()
        self._import_started_at = 0.0
        self._speed_samples: deque[tuple[float, float]] = deque()
        self._last_import_result = None
        self._source_panel_visible = True
        self._dest_panel_visible = True
        self._last_source_width = 240
        self._last_dest_width = 260

        self._theme_mode = get_theme_mode()
        T.set_dark(self._resolve_dark())
        self._build_ui()
        self._apply_theme()
        self._load_saved_config()

        # Follow macOS / Windows appearance changes while in System mode
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self._build_menu_bar()

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
        self._source_panel.card_inserted.connect(self._on_card_inserted)
        self._source_panel.drive_removed.connect(self._on_drive_removed)
        self._splitter.addWidget(self._source_panel)

        # Center: stacked file table / history
        self._stack = QStackedWidget()
        self._file_table = FileTable()
        self._history_panel = HistoryPanel()
        self._summary_panel = SummaryPanel()
        self._summary_panel.reveal_requested.connect(self._reveal_destination)
        self._summary_panel.eject_requested.connect(self._do_eject)
        self._summary_panel.report_requested.connect(self._do_save_report)
        self._summary_panel.retry_requested.connect(self._retry_failed)
        self._summary_panel.files_requested.connect(lambda: self._switch_view(_VIEW_FILES))
        self._stack.addWidget(self._file_table)      # _VIEW_FILES
        self._stack.addWidget(self._history_panel)   # _VIEW_HISTORY
        self._stack.addWidget(self._summary_panel)   # _VIEW_SUMMARY
        self._splitter.addWidget(self._stack)

        self._dest_panel = DestPanel()
        self._dest_panel.config_changed.connect(self._on_config_changed)
        self._splitter.addWidget(self._dest_panel)

        self._splitter.setSizes([240, 620, 260])
        self._splitter.setCollapsible(0, True)
        self._splitter.setCollapsible(1, False)
        self._splitter.setCollapsible(2, True)
        root.addWidget(self._splitter, stretch=1)

        root.addWidget(self._build_action_bar())

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)
        self._set_status("Ready — insert a camera card")

    def _build_menu_bar(self):
        self._menu_bar = self.menuBar()
        self._menu_bar.setNativeMenuBar(True)

        # Import menu — keyboard access to the main workflow
        self._import_menu = self._menu_bar.addMenu("Import")
        self._scan_action = QAction("Scan Card", self)
        self._scan_action.setShortcut(QKeySequence("Ctrl+R"))
        self._scan_action.triggered.connect(lambda: self._scan_btn.isEnabled() and self._do_scan())
        self._import_action = QAction("Import New Files", self)
        self._import_action.setShortcut(QKeySequence("Ctrl+I"))
        self._import_action.triggered.connect(lambda: self._import_btn.isEnabled() and self._do_import())
        self._cancel_action = QAction("Cancel Import", self)
        self._cancel_action.setShortcut(QKeySequence("Ctrl+."))
        self._cancel_action.triggered.connect(
            lambda: self._cancel_btn.isVisible() and self._cancel_btn.isEnabled() and self._do_cancel()
        )
        self._eject_action = QAction("Eject Card", self)
        self._eject_action.setShortcut(QKeySequence("Ctrl+E"))
        self._eject_action.triggered.connect(self._do_eject)
        for a in (self._scan_action, self._import_action, self._cancel_action):
            self._import_menu.addAction(a)
        self._import_menu.addSeparator()
        self._import_menu.addAction(self._eject_action)

        self._view_menu = self._menu_bar.addMenu("View")

        self._files_action = QAction("Files", self)
        self._files_action.setCheckable(True)
        self._files_action.setShortcut(QKeySequence("Ctrl+1"))
        self._files_action.triggered.connect(lambda _checked=False: self._switch_view(_VIEW_FILES))

        self._history_action = QAction("History", self)
        self._history_action.setCheckable(True)
        self._history_action.setShortcut(QKeySequence("Ctrl+2"))
        self._history_action.triggered.connect(lambda _checked=False: self._switch_view(_VIEW_HISTORY))

        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addAction(self._files_action)
        self._view_group.addAction(self._history_action)

        self._appearance_menu = QMenu("Appearance", self)
        self._appearance_group = QActionGroup(self)
        self._appearance_group.setExclusive(True)
        self._appearance_actions: dict[str, QAction] = {}
        for mode, label in (("system", "Match System"), ("light", "Light"), ("dark", "Dark")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, m=mode: self._set_theme_mode(m))
            self._appearance_group.addAction(action)
            self._appearance_menu.addAction(action)
            self._appearance_actions[mode] = action

        self._show_drives_action = QAction("Show Drives Sidebar", self)
        self._show_drives_action.setCheckable(True)
        self._show_drives_action.setChecked(True)
        self._show_drives_action.toggled.connect(self._set_source_panel_visible)

        self._show_destination_action = QAction("Show Destination Sidebar", self)
        self._show_destination_action.setCheckable(True)
        self._show_destination_action.setChecked(True)
        self._show_destination_action.toggled.connect(self._set_dest_panel_visible)

        self._view_menu.addAction(self._files_action)
        self._view_menu.addAction(self._history_action)
        self._view_menu.addSeparator()
        self._view_menu.addAction(self._show_drives_action)
        self._view_menu.addAction(self._show_destination_action)
        self._view_menu.addSeparator()
        self._view_menu.addMenu(self._appearance_menu)

        self._settings_menu = self._menu_bar.addMenu("Settings")
        self._folder_rules_action = QAction("Folder Naming Rules…", self)
        self._folder_rules_action.triggered.connect(self._open_settings)
        self._settings_menu.addAction(self._folder_rules_action)
        self._auto_scan_action = QAction("Scan New Cards Automatically", self)
        self._auto_scan_action.setCheckable(True)
        self._auto_scan_action.setChecked(get_auto_scan())
        self._auto_scan_action.toggled.connect(save_auto_scan)
        self._settings_menu.addAction(self._auto_scan_action)

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

    def _resolve_dark(self) -> bool:
        if self._theme_mode == "system":
            return system_prefers_dark()
        return self._theme_mode == "dark"

    def _set_theme_mode(self, mode: str):
        self._theme_mode = mode
        save_theme_mode(mode)
        T.set_dark(self._resolve_dark())
        self._apply_theme()

    def _on_system_scheme_changed(self, *_):
        if self._theme_mode != "system":
            return
        dark = system_prefers_dark()
        if dark != T.dark:
            T.set_dark(dark)
            self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(
            f"QMainWindow {{ background: {T.BG_BASE}; }}"
            f" QLabel {{ background: transparent; }}"
        )

        self._menu_bar.setStyleSheet(T.MENU_STYLE)

        # Toolbar
        self._toolbar.setStyleSheet(T.TOOLBAR_STYLE)
        self._app_title.setStyleSheet(f"color: {T.TEXT_PRIMARY};")
        self._header_status.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px;")
        self._sync_view_controls(self._stack.currentIndex())

        self._appearance_actions[self._theme_mode].setChecked(True)
        apply_app_palette()

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
        self._summary_panel.apply_theme()

    # ------------------------------------------------------------------
    # View switching
    # ------------------------------------------------------------------

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        self._sync_view_controls(index)
        if index == _VIEW_HISTORY:
            self._history_panel.load()

    def _sync_view_controls(self, index: int):
        # The summary isn't a menu view — leave both unchecked while it shows
        self._view_group.setExclusive(False)
        self._files_action.setChecked(index == _VIEW_FILES)
        self._history_action.setChecked(index == _VIEW_HISTORY)
        self._view_group.setExclusive(True)

    def _set_source_panel_visible(self, visible: bool):
        self._source_panel_visible = visible
        self._apply_splitter_visibility()

    def _set_dest_panel_visible(self, visible: bool):
        self._dest_panel_visible = visible
        self._apply_splitter_visibility()

    def _apply_splitter_visibility(self):
        sizes = self._splitter.sizes()
        if len(sizes) >= 3:
            if self._source_panel.isVisible() and sizes[0] > 0:
                self._last_source_width = sizes[0]
            if self._dest_panel.isVisible() and sizes[2] > 0:
                self._last_dest_width = sizes[2]

        self._source_panel.setVisible(self._source_panel_visible)
        self._dest_panel.setVisible(self._dest_panel_visible)

        total_width = sum(sizes) if sizes else max(self.width(), 1120)
        source_width = self._last_source_width if self._source_panel_visible else 0
        dest_width = self._last_dest_width if self._dest_panel_visible else 0
        center_width = max(420, total_width - source_width - dest_width)
        self._splitter.setSizes([source_width, center_width, dest_width])

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _open_settings(self):
        from .widgets.settings_panel import SettingsDialog
        dlg = SettingsDialog(get_rules(), parent=self)
        dlg.rules_saved.connect(self._on_rules_saved)
        dlg.exec()

    def _on_rules_saved(self, rules: dict):
        logger.info("Rules updated: %s", rules)
        self._dest_panel.set_templates(rules)
        if self._dest_config:
            self._dest_config.templates = rules
            self._replan()

    def _on_drive_selected(self, drive: DriveInfo):
        logger.info("Drive selected: %s (%s)", drive.label, drive.mount_point)
        self._header_status.setText(f"{drive.label}  ·  {drive.total_gb} GB")

        if drive.is_camera_card:
            self._selected_drive = drive
            protect(drive.mount_point)
            self._scan_btn.setEnabled(not self._importing and not self._scanning)
            self._set_status(f"Camera card: {drive.label}  —  click Scan to continue")
        elif drive.is_external_drive:
            self._dest_panel.set_drive_root(drive.mount_point)
            self._set_status(f"Destination set to {drive.label} ({drive.mount_point})")

    def _on_card_inserted(self, drive: DriveInfo):
        """A single new camera card appeared — select it, and scan if enabled."""
        if self._importing or self._scanning:
            return
        self._on_drive_selected(drive)
        if self._auto_scan_action.isChecked():
            self._do_scan()

    def _on_drive_removed(self, drive: DriveInfo):
        if self._selected_drive is None or drive.unique_id != self._selected_drive.unique_id:
            return
        self._selected_drive = None
        unprotect(drive.mount_point)
        self._scan_btn.setEnabled(False)
        self._header_status.setText("")
        self._summary_panel.set_eject_state("unavailable")
        if not self._importing and self._scan_result is not None:
            # Files on the table are no longer reachable
            self._import_btn.setEnabled(False)
        self._set_status(f"{drive.label} removed — insert a camera card")

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
        if self._scanning:
            self._scan_config_stale = True

        self._replan()

    def _replan(self):
        """
        Recompute which scanned files are new for the current destination and
        rules. Runs off the UI thread — planning stats every destination path,
        which can take seconds on a sleeping external drive.
        """
        if self._importing or self._scanning or not self._scan_result or not self._dest_config:
            return
        self._plan_generation += 1
        generation = self._plan_generation
        files = self._scan_result.files
        config = self._dest_config
        self._import_btn.setEnabled(False)
        self._set_status("Checking destination…")

        def _worker():
            try:
                plan = plan_import(files, config, verify_existing=False)
                new_set = {str(item.file.path) for item in plan.to_copy}
            except Exception as e:
                logger.error("Planning failed: %s", e)
                new_set = None
            self._sig.plan_done.emit(new_set, generation)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_plan_done(self, new_set: set[str] | None, generation: int):
        if generation != self._plan_generation or self._importing or not self._scan_result:
            return   # superseded by a newer config change
        if new_set is None:
            self._set_status("Could not check destination — see log for details")
            return
        self._show_scan_result(self._scan_result, new_set)

    def _do_scan(self):
        drive = self._selected_drive
        if drive is None or self._importing or self._scanning:
            return

        if self._dest_config and self._is_dest_drive(drive):
            self._set_status("Cannot scan destination drive — select your SD card instead.")
            return
        self._scan_config_stale = False

        self._scanning = True
        self._plan_generation += 1   # discard any in-flight replan
        self._scan_btn.setEnabled(False)
        self._import_btn.setEnabled(False)
        self._report_btn.setVisible(False)
        self._last_import_result = None
        self._file_table.clear()
        self._progress.setValue(0)
        self._set_status("Scanning SD card…")
        self._switch_view(0)
        logger.info("Scan started: %s", drive.mount_point)
        config = self._dest_config

        last_emit = [0.0]

        def _progress(phase: str, done: int, total: int):
            # Throttle: the scanner calls back once per file
            now = time.monotonic()
            if done < total and now - last_emit[0] < 0.1:
                return
            last_emit[0] = now
            self._sig.scan_progress.emit(phase, done, total)

        def _worker():
            try:
                result = scan_card(
                    drive.mount_point,
                    progress_cb=lambda done, total, _p: _progress("Finding files", done, total),
                )
                extract_all(
                    result.files,
                    progress_cb=lambda done, total: _progress("Reading metadata", done, total),
                )
                self._sig.scan_progress.emit("Checking destination", 0, 0)
                missing_date = [f for f in result.files if f.captured_at is None]
                if missing_date:
                    infos = inspect_all([f.path for f in missing_date])
                    info_map = {i.path: i for i in infos}
                    for f in missing_date:
                        info = info_map.get(f.path)
                        if info and info.captured_at:
                            f.captured_at = info.captured_at

                new_set: set[str] = set()
                if config:
                    plan = plan_import(result.files, config, verify_existing=False)
                    new_set = {str(item.file.path) for item in plan.to_copy}
                else:
                    new_set = {str(f.path) for f in result.files}

                self._sig.scan_done.emit(result, new_set)
            except Exception as e:
                logger.error("Scan failed: %s", e)
                self._sig.status.emit(f"Scan failed: {e}")
                self._sig.scan_done.emit(None, set())

        threading.Thread(target=_worker, daemon=True).start()

    def _on_scan_progress(self, phase: str, done: int, total: int):
        if total:
            self._progress.setValue(int(done / total * 100))
            self._set_status(f"{phase}…  {done} / {total}")
        else:
            self._set_status(f"{phase}…")

    def _on_scan_done(self, result, new_set: set[str]):
        self._scanning = False
        self._scan_result = result
        self._scan_btn.setEnabled(True)
        self._progress.setValue(0)

        if result is None:
            return

        self._show_scan_result(result, new_set)
        # Destination may have changed while the scan ran
        if self._dest_config is not None and self._scan_config_stale:
            self._replan()

    def _show_scan_result(self, result, new_set: set[str]):
        self._new_set = new_set
        self._file_table.load(result.files, new_set)
        self._dest_panel.set_samples(result.files)
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
        if not self._scan_result or not self._dest_config or self._importing or self._scanning:
            return

        new_files = [f for f in self._scan_result.files if str(f.path) in self._new_set]
        if not self._check_space(new_files):
            return

        source_label = self._selected_drive
        dlg = SessionNameDialog(
            file_count=len(new_files),
            source_label=source_label.label if source_label else "",
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        self._session_name = dlg.session_name()
        self._start_import(new_files)

    def _retry_failed(self):
        result = self._last_import_result
        if self._importing or not result or not result.failed or not self._dest_config:
            return
        files = [f for f, _ in result.failed]
        if not self._check_space(files):
            return
        self._start_import(files)

    def _check_space(self, new_files) -> bool:
        errors = check_batch_space(new_files, self._dest_config)
        if errors:
            total_needed = sum(f.size_bytes for f in new_files) / 1_073_741_824
            msg = QMessageBox(self)
            msg.setWindowTitle("Not Enough Space")
            msg.setIcon(QMessageBox.Critical)
            msg.setText(f"Not enough space to import {len(new_files)} files ({total_needed:.2f} GB total).")
            msg.setInformativeText("\n".join(errors))
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            return False
        return True

    def _start_import(self, new_files):
        config = self._dest_config
        session_name = self._session_name

        self._importing = True
        self._keep_awake.start()
        self._import_started_at = time.monotonic()
        self._speed_samples.clear()
        self._switch_view(_VIEW_FILES)
        self._report_btn.setVisible(False)
        self._plan_generation += 1   # discard any in-flight replan
        self._started_files.clear()
        self._source_panel.set_paused(True)
        self._import_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._cancel_event.clear()
        self._progress.setValue(0)
        self._file_progress.setValue(0)
        self._file_progress.setVisible(True)
        self._set_status("Importing…")
        logger.info("Import started: %d new files", len(new_files))

        files = new_files

        def _worker():
            def on_progress(done, total, name, bytes_done, bytes_total, file_bytes_done, file_bytes_total):
                self._sig.progress.emit(done, total, name, bytes_done, bytes_total, file_bytes_done, file_bytes_total)
            def on_verify_progress(name, bytes_done, bytes_total):
                self._sig.verify_progress.emit(name, bytes_done, bytes_total)
            def on_verify(name, ok):
                self._sig.verify_done.emit(name, ok)
            result = run_import(files, config, progress_cb=on_progress,
                                verify_cb=on_verify,
                                verify_progress_cb=on_verify_progress,
                                cancel_event=self._cancel_event,
                                session_name=session_name)
            self._sig.import_done.emit(result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, done: int, total: int, filename: str, bytes_done: float, bytes_total: float, file_bytes_done: float, file_bytes_total: float):
        overall = bytes_done / bytes_total if bytes_total else 1.0
        self._progress.setValue(int(overall * 100))

        file_progress = file_bytes_done / file_bytes_total if file_bytes_total else 1.0
        self._file_progress.setValue(int(file_progress * 1000))

        pct = int(overall * 100)
        self.setWindowTitle(f"{pct}% — Media Porter")
        self._set_status(
            f"Copying {done + 1 if done < total else done} of {total}  ·  "
            f"{format_size(bytes_done)} of {format_size(bytes_total)}"
            f"{self._speed_eta_text(bytes_done, bytes_total)}"
        )

        # Two files copy in parallel, so events interleave — only mark a file
        # in progress the first time we see it.
        if filename not in self._started_files:
            self._started_files.add(filename)
            self._file_table.mark_in_progress(filename)
        if file_bytes_done >= file_bytes_total and file_bytes_total > 0:
            self._file_table.mark_verifying(filename)

    def _speed_eta_text(self, bytes_done: float, bytes_total: float) -> str:
        """'  ·  85 MB/s  ·  about 6 min left' — empty until we have a stable rate."""
        now = time.monotonic()
        samples = self._speed_samples
        samples.append((now, bytes_done))
        while len(samples) > 2 and now - samples[0][0] > _SPEED_WINDOW_SEC:
            samples.popleft()
        t0, b0 = samples[0]
        if now - self._import_started_at < 3 or now - t0 < 1.5:
            return "  ·  estimating time…"
        rate = (bytes_done - b0) / (now - t0)
        if rate <= 0:
            return ""
        remaining = (bytes_total - bytes_done) / rate
        left = "less than a minute left" if remaining < 60 else f"about {format_duration(remaining)} left"
        return f"  ·  {rate / 1_048_576:.0f} MB/s  ·  {left}"

    def _on_verify_progress(self, filename: str, bytes_done: float, bytes_total: float):
        verify_progress = bytes_done / bytes_total if bytes_total else 1.0
        self._file_progress.setValue(int(verify_progress * 1000))
        mb_done = bytes_done / 1_048_576
        mb_total = bytes_total / 1_048_576
        self._set_status(f"Verifying  —  {filename}  ({mb_done:.0f} / {mb_total:.0f} MB)")
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
        self._keep_awake.stop()
        self.setWindowTitle("Media Porter")
        self._source_panel.set_paused(False)
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

        elapsed = time.monotonic() - self._import_started_at
        self._summary_panel.show_result(
            result,
            cancelled=cancelled,
            elapsed_sec=elapsed,
            can_eject=self._selected_drive is not None and self._selected_drive.is_camera_card,
        )
        self._switch_view(_VIEW_SUMMARY)
        self._announce_done(result, cancelled, elapsed)

    def _announce_done(self, result, cancelled: bool, elapsed: float):
        """Sound + system notification so people who walked away find out."""
        if cancelled:
            return
        problems = result.total_failed + result.total_verify_failed + result.total_conflicts
        n = result.total_copied
        if problems:
            title, message = "Import finished with problems", f"{n} copied · {problems} need attention"
        else:
            title = "Import complete"
            message = f"{n} files · {format_size(sum(f.size_bytes for f, _ in result.copied))} · {format_duration(elapsed)}"
        active = self.isActiveWindow()
        notify(title, message, success=not problems, banner=not active)
        if not active:
            QApplication.alert(self)   # bounce the Dock icon / flash the taskbar

    # ------------------------------------------------------------------
    # After import: reveal, eject
    # ------------------------------------------------------------------

    def _reveal_destination(self):
        result = self._last_import_result
        folder: Path | None = None
        if result and result.copied:
            parents = [str(dest.parent) for _, dest in result.copied]
            try:
                folder = Path(os.path.commonpath(parents))
            except ValueError:   # different drives on Windows
                folder = Path(parents[0])
        elif self._dest_config:
            folder = self._dest_config.photo_base
        while folder is not None and not folder.exists() and folder != folder.parent:
            folder = folder.parent
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _do_eject(self):
        drive = self._selected_drive
        if drive is None or not drive.is_camera_card:
            self._set_status("No camera card selected")
            return
        if self._importing or self._scanning:
            self._set_status("Wait for the current scan or import to finish before ejecting")
            return
        self._summary_panel.set_eject_state("busy")
        self._scan_btn.setEnabled(False)
        self._set_status(f"Ejecting {drive.label}…")

        def _worker():
            ok, message = eject(drive.mount_point)
            self._sig.eject_done.emit(ok, message)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_eject_done(self, ok: bool, message: str):
        drive = self._selected_drive
        if ok:
            if drive is not None:
                unprotect(drive.mount_point)
            self._selected_drive = None
            self._source_panel.clear_selection()
            self._source_panel.refresh()
            self._header_status.setText("")
            self._summary_panel.set_eject_state("done")
            self._set_status(message)
        else:
            self._summary_panel.set_eject_state("ready")
            self._scan_btn.setEnabled(drive is not None)
            self._set_status(message)
            QMessageBox.warning(self, "Couldn't Eject Card", message)

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._importing:
            answer = QMessageBox.question(
                self,
                "Import in Progress",
                "Files are still being copied. Quit anyway?\n\n"
                "Files already copied are kept; the rest can be imported next time.",
                QMessageBox.Cancel | QMessageBox.Yes,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._cancel_event.set()
        self._keep_awake.stop()
        event.accept()

    def _do_save_report(self):
        if not self._last_import_result:
            return
        from backend.core.report import write_report
        from datetime import datetime

        default_dir = str(self._dest_config.photo_base.parent) if self._dest_config else str(Path.home())
        safe_name = re.sub(r"[^\w-]+", "_", self._session_name).strip("_")
        slug = f"_{safe_name}" if safe_name else ""
        default_name = f"media-porter-report_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}{slug}.csv"

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
                                   report_path=dest_path)
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
