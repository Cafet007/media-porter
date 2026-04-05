"""
File Table — shows scanned media files with kind, date, size, status.
No internal header bar; includes an empty state view.
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QStyledItemDelegate, QStyleOptionViewItem
)
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QFont, QColor, QPainter, QPainterPath, QBrush

from backend.core.models import MediaFile, MediaType
from gui.theme import T


_KIND_LABEL = {
    MediaType.RAW:     "RAW",
    MediaType.PHOTO:   "JPG",
    MediaType.VIDEO:   "VIDEO",
    MediaType.UNKNOWN: "?",
}

_KIND_COLORS_DARK = {
    MediaType.RAW:     ("#3d2600", "#ffd60a"),
    MediaType.PHOTO:   ("#0d3318", "#30d158"),
    MediaType.VIDEO:   ("#002650", "#0a84ff"),
    MediaType.UNKNOWN: ("#2c2c2e", "#8e8e93"),
}
_KIND_COLORS_LIGHT = {
    MediaType.RAW:     ("#fff0cc", "#7a4a00"),
    MediaType.PHOTO:   ("#d4f7e0", "#1a7a35"),
    MediaType.VIDEO:   ("#d0e8ff", "#004fb3"),
    MediaType.UNKNOWN: ("#f2f2f7", "#8e8e93"),
}


class _BadgeDelegate(QStyledItemDelegate):
    """Draws a coloured pill badge for the Kind column."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        if option.state & 0x0200:  # State_Selected
            painter.fillRect(option.rect, QColor(T.BG_CARD_SEL))

        text = index.data(Qt.DisplayRole) or ""
        media_type = index.data(Qt.UserRole)
        if not text or media_type is None:
            return

        cmap = _KIND_COLORS_DARK if T.dark else _KIND_COLORS_LIGHT
        bg_hex, fg_hex = cmap.get(media_type, cmap[MediaType.UNKNOWN])

        painter.setRenderHint(QPainter.Antialiasing)

        f = QFont()
        f.setPixelSize(10)
        f.setBold(True)
        painter.setFont(f)
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        bw, bh = text_w + 16, 20
        x = option.rect.x() + (option.rect.width()  - bw) // 2
        y = option.rect.y() + (option.rect.height() - bh) // 2

        path = QPainterPath()
        path.addRoundedRect(x, y, bw, bh, 5, 5)
        painter.fillPath(path, QBrush(QColor(bg_hex)))
        painter.setPen(QColor(fg_hex))
        painter.drawText(QRect(x, y, bw, bh), Qt.AlignCenter, text)

    def sizeHint(self, option, index) -> QSize:
        return QSize(72, 32)


class _SortableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key=None):
        super().__init__(text)
        self._sort_key = sort_key if sort_key is not None else text

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortableItem):
            try:
                return self._sort_key < other._sort_key
            except TypeError:
                pass
        return super().__lt__(other)


class FileTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Summary bar
        self._summary_bar = QWidget()
        self._summary_bar.setFixedHeight(36)
        sb_layout = QHBoxLayout(self._summary_bar)
        sb_layout.setContentsMargins(16, 0, 16, 0)

        self._summary = QLabel("")
        sf = QFont()
        sf.setPixelSize(12)
        self._summary.setFont(sf)
        sb_layout.addWidget(self._summary)
        sb_layout.addStretch()

        layout.addWidget(self._summary_bar)

        # Divider under summary bar
        div = QWidget()
        div.setFixedHeight(1)
        self._summary_div = div
        layout.addWidget(div)

        # Empty state
        self._empty = QWidget()
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setAlignment(Qt.AlignCenter)

        empty_icon = QLabel("📂")
        empty_icon.setFont(QFont("Arial", 40))
        empty_icon.setAlignment(Qt.AlignCenter)

        empty_title = QLabel("No files scanned yet")
        etf = QFont()
        etf.setPixelSize(15)
        etf.setBold(True)
        empty_title.setFont(etf)
        empty_title.setAlignment(Qt.AlignCenter)

        empty_sub = QLabel("Select a camera card from the sidebar\nand click Scan Card to begin.")
        empty_sub.setAlignment(Qt.AlignCenter)
        empty_sub.setWordWrap(True)

        self._empty_title = empty_title
        self._empty_sub   = empty_sub

        empty_layout.addStretch()
        empty_layout.addWidget(empty_icon)
        empty_layout.addSpacing(12)
        empty_layout.addWidget(empty_title)
        empty_layout.addSpacing(6)
        empty_layout.addWidget(empty_sub)
        empty_layout.addStretch()

        layout.addWidget(self._empty, stretch=1)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["File", "Kind", "Date", "Size", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.setColumnWidth(1, 76)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSortIndicatorShown(True)
        self._table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)

        self._badge_delegate = _BadgeDelegate(self._table)
        self._table.setItemDelegateForColumn(1, self._badge_delegate)
        self._table.hide()

        layout.addWidget(self._table, stretch=1)
        self.apply_theme()

    def apply_theme(self):
        self._summary_bar.setStyleSheet(
            f"background: {T.BG_TABLE_HDR}; border-bottom: 0px;"
        )
        self._summary_div.setStyleSheet(f"background: {T.DIVIDER};")
        self._summary.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
        self._empty.setStyleSheet(f"background: {T.BG_TABLE};")
        self._empty_title.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        self._empty_sub.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 13px; background: transparent;")
        self._table.setStyleSheet(T.TABLE_STYLE)

    def load(self, files: list[MediaFile], new_set: set[str] | None = None):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(files))

        new_count = skipped_count = 0

        for row, f in enumerate(files):
            is_new = new_set is None or f.name in new_set
            if is_new:
                new_count += 1
            else:
                skipped_count += 1

            date_str = f.captured_at.strftime("%Y-%m-%d  %H:%M") if f.captured_at else "—"
            date_key = f.captured_at.timestamp() if f.captured_at else 0.0
            size_str = f"{f.size_mb:.1f} MB"
            status_str   = "New" if is_new else "Already imported"
            status_color = QColor(T.ACCENT if is_new else T.TEXT_MUTED)

            name_item = QTableWidgetItem(f.name)
            name_item.setForeground(QColor(T.TEXT_PRIMARY))

            kind_item = QTableWidgetItem(_KIND_LABEL.get(f.media_type, "?"))
            kind_item.setData(Qt.UserRole, f.media_type)
            kind_item.setTextAlignment(Qt.AlignCenter)

            date_item = _SortableItem(date_str, sort_key=date_key)
            date_item.setForeground(QColor(T.TEXT_SECONDARY))

            size_item = _SortableItem(size_str, sort_key=f.size_mb)
            size_item.setForeground(QColor(T.TEXT_SECONDARY))

            status_item = QTableWidgetItem(status_str)
            status_item.setForeground(status_color)

            for col, item in enumerate([name_item, kind_item, date_item, size_item, status_item]):
                self._table.setItem(row, col, item)
            self._table.setRowHeight(row, 32)

        self._table.setSortingEnabled(True)

        total_mb = sum(f.size_mb for f in files)
        self._summary.setText(
            f"{len(files)} files  ·  {total_mb:.0f} MB  ·  "
            f"{new_count} new  ·  {skipped_count} already imported"
        )

        self._empty.hide()
        self._table.show()

    def _update_status(self, filename: str, text: str, color: str):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text() == filename:
                si = QTableWidgetItem(text)
                si.setForeground(QColor(color))
                self._table.setItem(row, 4, si)
                break

    def mark_in_progress(self, filename: str):
        self._update_status(filename, "In Progress…", T.WARNING)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text() == filename:
                self._table.scrollToItem(self._table.item(row, 4))
                break

    def mark_copied(self, filename: str):
        self._update_status(filename, "Copied ✓", T.SUCCESS)

    def mark_conflict(self, filename: str):
        self._update_status(filename, "Conflict ⚠", T.CONFLICT)

    def mark_failed(self, filename: str):
        self._update_status(filename, "Failed ✗", T.DANGER)

    def clear(self):
        self._table.setRowCount(0)
        self._table.hide()
        self._empty.show()
        self._summary.setText("")
