"""
History Panel — shows past import records from the database.
No internal header bar.
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from gui.theme import T


class HistoryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Slim action bar (matches FileTable summary bar height)
        self._bar = QWidget()
        self._bar.setFixedHeight(36)
        bar_layout = QHBoxLayout(self._bar)
        bar_layout.setContentsMargins(16, 0, 16, 0)
        bar_layout.setSpacing(8)

        self._count_lbl = QLabel("")
        cf = QFont()
        cf.setPixelSize(12)
        self._count_lbl.setFont(cf)
        bar_layout.addWidget(self._count_lbl)
        bar_layout.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedHeight(26)
        self._refresh_btn.clicked.connect(self.load)
        bar_layout.addWidget(self._refresh_btn)

        layout.addWidget(self._bar)

        div = QWidget()
        div.setFixedHeight(1)
        self._bar_div = div
        layout.addWidget(div)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["File", "Type", "Camera", "Captured", "Imported", "Destination"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, stretch=1)

        # Empty state
        self._empty_lbl = QLabel("No import history yet.\nFiles will appear here after your first import.")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setFont(QFont("Arial", 14))
        self._empty_lbl.hide()
        layout.addWidget(self._empty_lbl)

        self.apply_theme()

    def apply_theme(self):
        self._bar.setStyleSheet(f"background: {T.BG_TABLE_HDR};")
        self._bar_div.setStyleSheet(f"background: {T.DIVIDER};")
        self._count_lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
        self._refresh_btn.setStyleSheet(T.small_btn_style())
        self._table.setStyleSheet(T.TABLE_STYLE)
        self.setStyleSheet(
            f"HistoryPanel {{ background: {T.BG_TABLE}; }}"
            f" QLabel {{ background: transparent; border: none; }}"
        )
        self._empty_lbl.setStyleSheet(f"color: {T.TEXT_MUTED};")

    def load(self):
        try:
            from backend.db.repository import get_history
            records = get_history(limit=1000)
        except Exception:
            records = []

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        self._table.setVisible(bool(records))
        self._empty_lbl.setVisible(not records)

        for row, rec in enumerate(records):
            from pathlib import Path
            filename   = Path(rec.source_path).name if rec.source_path else "—"
            media_type = rec.media_type or "—"
            camera     = " ".join(filter(None, [rec.camera_make, rec.camera_model])) or "—"
            captured   = rec.captured_at.strftime("%Y-%m-%d  %H:%M") if rec.captured_at else "—"
            imported   = rec.imported_at.strftime("%Y-%m-%d  %H:%M") if rec.imported_at else "—"
            dest       = rec.dest_path or "—"

            for col, text in enumerate([filename, media_type, camera, captured, imported, dest]):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(T.TEXT_PRIMARY if col == 0 else T.TEXT_SECONDARY))
                self._table.setItem(row, col, item)
            self._table.setRowHeight(row, 32)

        self._table.setSortingEnabled(True)
        self._count_lbl.setText(f"{len(records)} records" if records else "")
