"""
File Table — browse scanned media and choose what to import.

  ┌──────────────────────────────────────────────────────────────┐
  │ 412 files · 38 GB · 380 new           120 selected · 9.8 GB  │  summary
  │ [New only] [All][RAW][JPG][Video] [Search…]   Select All·None │  filters
  │                                                  [List][Grid]│
  ├──────────────────────────────────────────────────────────────┤
  │ ☑ Sat, Oct 18, 2026 · 212 files · 18.4 GB                    │  list view:
  │   ☑ ▣ DSC0001.ARW   RAW  09:30:12  24.1 MB  New              │  date groups
  │   …                                                          │
  └──────────────────────────────────────────────────────────────┘

Model/view design so thousands of files stay fast:
  FileModel   — date groups → files, check state, status, thumbnails
  FileFilter  — kind / new-only / name search on top of the model
  QTreeView   — grouped list;  QListView (IconMode) — flat thumbnail grid

Thumbnails are requested lazily while painting (so only visible rows load)
and generated on background threads by ThumbnailLoader.

The public API (load / mark_* / clear / set_scan_info) is name-based to
match the importer's progress callbacks.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QButtonGroup, QTreeView, QListView, QStackedWidget, QAbstractItemView,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem, QHeaderView,
)
from PySide6.QtCore import (
    Qt, QAbstractItemModel, QModelIndex, QSortFilterProxyModel, QSize,
    QRect, QRectF, QPointF, Signal, QEvent, QTimer,
)
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPainterPath, QBrush, QPixmap, QImage, QPen,
    QPolygonF, QGuiApplication,
)

from backend.core.models import MediaFile, MediaType
from backend.core.messages import format_size
from gui.icons import indicator_style
from gui.theme import T
from gui.thumb_loader import ThumbnailLoader


COL_NAME, COL_KIND, COL_TIME, COL_SIZE, COL_STATUS = range(5)
_HEADERS = ["File", "Kind", "Time", "Size", "Status"]

SORT_ROLE  = Qt.UserRole + 1
KIND_ROLE  = Qt.UserRole + 2
NODE_ROLE  = Qt.UserRole + 3
THUMB_ROLE = Qt.UserRole + 4   # grid-size pixmap (or None)

_LIST_THUMB = QSize(54, 36)
_ROW_HEIGHT = 44   # every row the same height → the tree never re-measures rows
_GRID_THUMB = QSize(270, 180)   # cached grid pixmap size; drawn scaled to the card
_GRID_CELL  = QSize(188, 176)   # initial cell; resized to fill the width (see _fit_grid)
_GRID_MIN_W = 180               # narrowest card before dropping a column
_GRID_TEXT_H = 64               # card height below the thumbnail (name + status)
_GRID_CACHE_LIMIT = 240         # grid pixmaps kept in memory (LRU)

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

# Filter chip → media types it shows (None = all)
_KIND_FILTERS = {
    "All":   None,
    "RAW":   {MediaType.RAW},
    "JPG":   {MediaType.PHOTO},
    "Video": {MediaType.VIDEO},
}


def _kind_colors(media_type: MediaType) -> tuple[str, str]:
    cmap = _KIND_COLORS_DARK if T.dark else _KIND_COLORS_LIGHT
    return cmap.get(media_type, cmap[MediaType.UNKNOWN])


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class _Node:
    __slots__ = ("file", "parent", "children", "row", "label", "date_key",
                 "checked", "checkable", "is_new", "status", "status_color",
                 "n_checkable", "n_checked", "total_bytes")

    def __init__(self, file: MediaFile | None = None, parent: "_Node | None" = None):
        self.file = file
        self.parent = parent
        self.children: list[_Node] = []
        self.row = 0
        self.label = ""
        self.date_key = 0.0
        self.checked = False
        self.checkable = False
        self.is_new = False
        self.status = ""
        self.status_color = ""
        # group-only aggregates
        self.n_checkable = 0
        self.n_checked = 0
        self.total_bytes = 0

    @property
    def is_group(self) -> bool:
        return self.file is None


class FileModel(QAbstractItemModel):
    selection_changed = Signal(int, object)   # checked file count, checked bytes (may exceed 32-bit)

    def __init__(self, loader: ThumbnailLoader, parent=None):
        super().__init__(parent)
        self._loader = loader
        self._loader.ready.connect(self._on_thumb_ready)
        self._grouped = True
        self._locked = False
        self._groups: list[_Node] = []
        self._files: list[_Node] = []
        self._by_name: dict[str, _Node] = {}
        self._by_path: dict[str, _Node] = {}
        self._user_unchecked: set[str] = set()
        self._checked_count = 0
        self._checked_bytes = 0
        # Thumbnails: list-size kept for all files, grid-size in an LRU
        self._list_thumbs: dict[str, QPixmap] = {}
        self._grid_thumbs: OrderedDict[str, QPixmap] = OrderedDict()
        self._no_preview: set[str] = set()
        self._images_ready: set[str] = set()
        self._dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0

    # ---- loading -------------------------------------------------------

    def load(self, files: list[MediaFile], new_set: set[str] | None, *, keep_selection: bool):
        if not keep_selection:
            self._user_unchecked.clear()
            self._loader.reset()
            self._list_thumbs.clear()
            self._grid_thumbs.clear()
            self._no_preview.clear()
            self._images_ready.clear()

        self.beginResetModel()
        self._locked = False
        self._files = []
        self._by_name = {}
        self._by_path = {}
        self._checked_count = 0
        self._checked_bytes = 0

        groups: dict[str, _Node] = {}
        for f in files:
            node = _Node(f)
            key = str(f.path)
            node.is_new = new_set is None or key in new_set
            node.checkable = node.is_new
            node.checked = node.is_new and key not in self._user_unchecked
            node.status = "New" if node.is_new else "Already imported"
            node.status_color = "accent" if node.is_new else "muted"

            day = f.captured_at.date() if f.captured_at else None
            gkey = day.isoformat() if day else "unknown"
            group = groups.get(gkey)
            if group is None:
                group = _Node()
                group.label = f"{day:%a, %b} {day.day}, {day.year}" if day else "Unknown date"
                group.date_key = float(day.toordinal()) if day else 0.0
                groups[gkey] = group
            node.parent = group
            group.children.append(node)
            group.total_bytes += f.size_bytes
            if node.checkable:
                group.n_checkable += 1
            if node.checked:
                group.n_checked += 1
                self._checked_count += 1
                self._checked_bytes += f.size_bytes

            self._files.append(node)
            self._by_name.setdefault(f.name, node)
            self._by_path[key] = node

        self._groups = sorted(groups.values(), key=lambda g: g.date_key)
        self._renumber()
        self.endResetModel()
        self.selection_changed.emit(self._checked_count, self._checked_bytes)

    def clear(self):
        self.load([], set(), keep_selection=False)

    def set_grouped(self, grouped: bool):
        if grouped == self._grouped:
            return
        self.beginResetModel()
        self._grouped = grouped
        self._renumber()
        self.endResetModel()

    def set_locked(self, locked: bool):
        """Lock check boxes while an import runs."""
        if locked == self._locked:
            return
        self._locked = locked
        self._emit_all_changed()

    def _renumber(self):
        for i, g in enumerate(self._groups):
            g.row = i
            for j, child in enumerate(g.children):
                child.row = j
        if not self._grouped:
            for i, node in enumerate(self._files):
                node.row = i

    def _top(self) -> list[_Node]:
        return self._groups if self._grouped else self._files

    # ---- queries -------------------------------------------------------

    def checked_files(self) -> list[MediaFile]:
        return [n.file for n in self._files if n.checked]

    def selection_summary(self) -> tuple[int, int]:
        return self._checked_count, self._checked_bytes

    def node_for_name(self, name: str) -> _Node | None:
        return self._by_name.get(name)

    def index_for_node(self, node: _Node, column: int = COL_NAME) -> QModelIndex:
        return self.createIndex(node.row, column, node)

    def has_files(self) -> bool:
        return bool(self._files)

    # ---- checking ------------------------------------------------------

    def set_checked(self, nodes: list[_Node], checked: bool):
        """Check/uncheck many files at once (one selection_changed emit)."""
        if self._locked:
            return
        touched_groups: set[int] = set()
        changed: list[_Node] = []
        for node in nodes:
            if node.is_group or not node.checkable or node.checked == checked:
                continue
            node.checked = checked
            delta = 1 if checked else -1
            self._checked_count += delta
            self._checked_bytes += delta * node.file.size_bytes
            node.parent.n_checked += delta
            key = str(node.file.path)
            if checked:
                self._user_unchecked.discard(key)
            else:
                self._user_unchecked.add(key)
            touched_groups.add(id(node.parent))
            changed.append(node)
        if not changed:
            return
        # One dataChanged per contiguous block (per group) — emitting per file
        # makes Select All on a big card take seconds.
        roles = [Qt.CheckStateRole]
        if self._grouped:
            for g in self._groups:
                if id(g) not in touched_groups:
                    continue
                gi = self.index_for_node(g)
                self.dataChanged.emit(gi, gi, roles)
                self.dataChanged.emit(self.index(0, 0, gi), self.index(len(g.children) - 1, 0, gi), roles)
        else:
            rows = [n.row for n in changed]
            self.dataChanged.emit(self.index(min(rows), 0), self.index(max(rows), 0), roles)
        self.selection_changed.emit(self._checked_count, self._checked_bytes)

    # ---- status --------------------------------------------------------

    def set_status(self, name: str, text: str, color: str) -> _Node | None:
        node = self._by_name.get(name)
        if node is None or (node.status == text and node.status_color == color):
            return node
        node.status = text
        node.status_color = color
        left = self.index_for_node(node, COL_NAME)
        right = self.index_for_node(node, COL_STATUS)
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.ForegroundRole])
        return node

    # ---- thumbnails ----------------------------------------------------

    def _list_thumb(self, node: _Node) -> QPixmap:
        key = str(node.file.path)
        pix = self._list_thumbs.get(key)
        if pix is None:
            if key not in self._no_preview:
                self._loader.request(node.file.path, node.file.media_type)
            return _placeholder(node.file.media_type, _LIST_THUMB, self._dpr)
        return pix

    def grid_thumb(self, node: _Node) -> QPixmap | None:
        key = str(node.file.path)
        pix = self._grid_thumbs.get(key)
        if pix is not None:
            self._grid_thumbs.move_to_end(key)
            return pix
        if key not in self._no_preview:
            self._loader.request(node.file.path, node.file.media_type)
        return None

    def _on_thumb_ready(self, key: str, image: QImage):
        node = self._by_path.get(key)
        if node is None:
            return
        if image.isNull():
            self._no_preview.add(key)
        else:
            self._list_thumbs[key] = _scaled(image, _LIST_THUMB, self._dpr)
            self._grid_thumbs[key] = _scaled(image, _GRID_THUMB, self._dpr)
            while len(self._grid_thumbs) > _GRID_CACHE_LIMIT:
                self._grid_thumbs.popitem(last=False)
        idx = self.index_for_node(node)
        self.dataChanged.emit(idx, idx, [Qt.DecorationRole, THUMB_ROLE])

    def _emit_all_changed(self):
        top = self._top()
        if not top:
            return
        self.dataChanged.emit(
            self.index(0, 0), self.index(len(top) - 1, len(_HEADERS) - 1),
        )
        if self._grouped:
            for g in self._groups:
                if g.children:
                    gi = self.index_for_node(g)
                    self.dataChanged.emit(
                        self.index(0, 0, gi),
                        self.index(len(g.children) - 1, len(_HEADERS) - 1, gi),
                    )

    # ---- QAbstractItemModel -------------------------------------------

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid():
            pnode: _Node = parent.internalPointer()
            if not pnode.is_group or not (0 <= row < len(pnode.children)):
                return QModelIndex()
            return self.createIndex(row, column, pnode.children[row])
        top = self._top()
        if not (0 <= row < len(top)):
            return QModelIndex()
        return self.createIndex(row, column, top[row])

    def parent(self, index=QModelIndex()):
        if not index.isValid():
            return QModelIndex()
        node: _Node = index.internalPointer()
        if not self._grouped or node.is_group or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return len(self._top())
        node: _Node = parent.internalPointer()
        return len(node.children) if (self._grouped and node.is_group) else 0

    def columnCount(self, parent=QModelIndex()):
        return len(_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return _HEADERS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        node: _Node = index.internalPointer()
        flags = Qt.ItemIsSelectable
        # Already-imported name cells are disabled: greyed box and thumbnail
        if node.is_group or node.checkable or index.column() != COL_NAME:
            flags |= Qt.ItemIsEnabled
        if index.column() == COL_NAME and not self._locked:
            if node.is_group and node.n_checkable:
                flags |= Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate
            elif not node.is_group and node.checkable:
                flags |= Qt.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node: _Node = index.internalPointer()
        col = index.column()

        if role == NODE_ROLE:
            return node

        if node.is_group:
            return self._group_data(node, col, role)

        f = node.file
        if role == Qt.DisplayRole:
            if col == COL_NAME:
                return f.name
            if col == COL_KIND:
                return _KIND_LABEL.get(f.media_type, "?")
            if col == COL_TIME:
                if not f.captured_at:
                    return "—"
                return f"{f.captured_at:%H:%M:%S}" if self._grouped else f"{f.captured_at:%Y-%m-%d  %H:%M}"
            if col == COL_SIZE:
                return f"{f.size_mb:.1f} MB"
            if col == COL_STATUS:
                return node.status
        elif role == SORT_ROLE:
            if col == COL_NAME:
                return f.name.lower()
            if col == COL_KIND:
                return _KIND_LABEL.get(f.media_type, "?")
            if col == COL_TIME:
                return f.captured_at.timestamp() if f.captured_at else 0.0
            if col == COL_SIZE:
                return f.size_bytes
            if col == COL_STATUS:
                return node.status
        elif role == Qt.CheckStateRole and col == COL_NAME:
            # Already-imported files get an (inert) box too so thumbnails line up
            return Qt.Checked if node.checked else Qt.Unchecked
        elif role == Qt.DecorationRole and col == COL_NAME:
            return self._list_thumb(node)
        elif role == THUMB_ROLE:
            return self.grid_thumb(node)
        elif role == KIND_ROLE:
            return f.media_type
        elif role == Qt.ForegroundRole:
            if col == COL_STATUS:
                return QColor(_status_color(node.status_color))
            if col in (COL_TIME, COL_SIZE):
                return QColor(T.TEXT_SECONDARY)
            return QColor(T.TEXT_PRIMARY if node.is_new else T.TEXT_SECONDARY)
        elif role == Qt.ToolTipRole:
            return str(f.path)
        elif role == Qt.SizeHintRole:
            return QSize(-1, _ROW_HEIGHT)
        elif role == Qt.TextAlignmentRole and col == COL_KIND:
            return Qt.AlignCenter
        return None

    def _group_data(self, node: _Node, col: int, role):
        if role == Qt.DisplayRole and col == COL_NAME:
            n = len(node.children)
            return f"{node.label}   ·   {n} file{'s' if n != 1 else ''}   ·   {format_size(node.total_bytes)}"
        if role == SORT_ROLE:
            return node.date_key
        if role == Qt.CheckStateRole and col == COL_NAME and node.n_checkable:
            if node.n_checked == 0:
                return Qt.Unchecked
            if node.n_checked == node.n_checkable:
                return Qt.Checked
            return Qt.PartiallyChecked
        if role == Qt.FontRole:
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ForegroundRole:
            return QColor(T.TEXT_PRIMARY)
        if role == Qt.BackgroundRole:
            return QColor(T.BG_TABLE_HDR)
        if role == Qt.SizeHintRole:
            return QSize(-1, _ROW_HEIGHT)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        node: _Node = index.internalPointer()
        checked = Qt.CheckState(value) == Qt.Checked
        if node.is_group:
            # A group with some unchecked files: clicking checks the rest
            if node.n_checked < node.n_checkable:
                checked = True
            self.set_checked(node.children, checked)
        else:
            self.set_checked([node], checked)
        return True


def _status_color(key: str) -> str:
    return {
        "accent": T.ACCENT, "muted": T.TEXT_MUTED, "warning": T.WARNING,
        "success": T.SUCCESS, "danger": T.DANGER, "conflict": T.CONFLICT,
    }.get(key, T.TEXT_SECONDARY)


def _scaled(image: QImage, box: QSize, dpr: float) -> QPixmap:
    target = QSize(int(box.width() * dpr), int(box.height() * dpr))
    pix = QPixmap.fromImage(image.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    pix.setDevicePixelRatio(dpr)
    return pix


_placeholder_cache: dict[tuple, QPixmap] = {}


def _placeholder(media_type: MediaType, box: QSize, dpr: float) -> QPixmap:
    """Neutral tile shown until (or instead of) a thumbnail."""
    key = (media_type, box.width(), box.height(), T.dark, dpr)
    pix = _placeholder_cache.get(key)
    if pix is not None:
        return pix
    pix = QPixmap(int(box.width() * dpr), int(box.height() * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, box.width(), box.height()), 4, 4)
    p.fillPath(path, QColor(T.BG_CARD if T.dark else "#e5e5ea"))
    if media_type == MediaType.VIDEO:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T.TEXT_MUTED))
        cx, cy, r = box.width() / 2, box.height() / 2, min(box.width(), box.height()) / 5
        p.drawPolygon(QPolygonF([QPointF(cx - r * 0.7, cy - r), QPointF(cx - r * 0.7, cy + r), QPointF(cx + r, cy)]))
    p.end()
    _placeholder_cache[key] = pix
    return pix


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

class FileFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRecursiveFilteringEnabled(True)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(False)   # don't re-sort on every status update
        self._kinds: set[MediaType] | None = None
        self._new_only = False
        self._text = ""

    def set_filters(self, *, kinds: set[MediaType] | None, new_only: bool, text: str):
        self._kinds = kinds
        self._new_only = new_only
        self._text = text.strip().lower()
        self.invalidateFilter()

    def is_filtered(self) -> bool:
        return self._kinds is not None or self._new_only or bool(self._text)

    def filterAcceptsRow(self, source_row, source_parent):
        if source_parent.isValid():
            siblings = source_parent.internalPointer().children
        else:
            siblings = self.sourceModel()._top()
        if not (0 <= source_row < len(siblings)):
            return False
        node: _Node = siblings[source_row]
        if node.is_group:
            return False   # groups show only through matching children
        f = node.file
        if self._kinds is not None and f.media_type not in self._kinds:
            return False
        if self._new_only and not node.is_new:
            return False
        if self._text and self._text not in f.name.lower():
            return False
        return True

    def setData(self, index, value, role=Qt.EditRole):
        # Checking a group only affects the files currently visible in it
        node: _Node = index.data(NODE_ROLE)
        if role == Qt.CheckStateRole and node is not None and node.is_group:
            children = [
                self.index(r, 0, index).data(NODE_ROLE)
                for r in range(self.rowCount(index))
            ]
            checkable = [c for c in children if c.checkable]
            checked = not all(c.checked for c in checkable)
            self.sourceModel().set_checked(checkable, checked)
            return True
        return super().setData(index, value, role)

    def visible_nodes(self) -> list[_Node]:
        nodes: list[_Node] = []
        for r in range(self.rowCount()):
            top = self.index(r, 0)
            node = top.data(NODE_ROLE)
            if node.is_group:
                nodes.extend(self.index(c, 0, top).data(NODE_ROLE) for c in range(self.rowCount(top)))
            else:
                nodes.append(node)
        return nodes


# ---------------------------------------------------------------------------
# Delegates
# ---------------------------------------------------------------------------

class _BadgeDelegate(QStyledItemDelegate):
    """Draws a coloured pill badge for the Kind column."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        node = index.data(NODE_ROLE)
        if node is None or node.is_group:
            return super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(T.BG_CARD_SEL))
        _draw_badge(painter, option.rect.center().x(), option.rect.center().y(), node.file.media_type)


def _draw_badge(painter: QPainter, cx: int, cy: int, media_type: MediaType, *, small: bool = False):
    text = _KIND_LABEL.get(media_type, "?")
    bg_hex, fg_hex = _kind_colors(media_type)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    f = QFont()
    f.setPixelSize(9 if small else 10)
    f.setBold(True)
    painter.setFont(f)
    fm = painter.fontMetrics()
    bw, bh = fm.horizontalAdvance(text) + (10 if small else 16), (16 if small else 20)
    x, y = cx - bw // 2, cy - bh // 2
    path = QPainterPath()
    path.addRoundedRect(x, y, bw, bh, 5, 5)
    painter.fillPath(path, QBrush(QColor(bg_hex)))
    painter.setPen(QColor(fg_hex))
    painter.drawText(QRect(x, y, bw, bh), Qt.AlignCenter, text)
    painter.restore()


class _GridDelegate(QStyledItemDelegate):
    """Thumbnail card: image, check circle, kind badge, name and status."""

    CHECK = 22

    def sizeHint(self, option, index) -> QSize:
        view = option.widget
        return view.gridSize() if isinstance(view, QListView) else _GRID_CELL

    def _check_rect(self, rect: QRect) -> QRect:
        return QRect(rect.x() + 16, rect.y() + 14, self.CHECK, self.CHECK)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        node: _Node = index.data(NODE_ROLE)
        if node is None or node.is_group:
            return
        model: FileModel = index.model().sourceModel()
        r = option.rect.adjusted(6, 4, -6, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # Card
        card = QPainterPath()
        card.addRoundedRect(QRectF(r), 10, 10)
        painter.fillPath(card, QColor(T.BG_CARD_SEL if selected else T.BG_CARD))
        if selected or node.checked:
            painter.setPen(QPen(QColor(T.ACCENT), 2 if selected else 1.2))
            painter.drawPath(card)

        # Thumbnail, letterboxed in a 3:2 box that grows with the card
        box_w = r.width() - 8
        box = QRect(r.x() + 4, r.y() + 4, box_w, round(box_w * 2 / 3))
        tile = QPainterPath()
        tile.addRoundedRect(QRectF(box), 7, 7)
        painter.fillPath(tile, QColor("#000000" if T.dark else "#e5e5ea"))
        pix = index.data(THUMB_ROLE)
        if pix is None:
            pix = _placeholder(node.file.media_type, box.size(), model._dpr)
        size = (pix.size() / pix.devicePixelRatio()).scaled(box.size(), Qt.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(box.center())
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setClipPath(tile)
        painter.drawPixmap(target, pix)
        painter.setClipping(False)

        if not node.is_new:
            painter.fillPath(tile, QColor(0, 0, 0, 110))   # dim already-imported

        # Kind badge (top-right)
        _draw_badge(painter, box.right() - 22, box.top() + 14, node.file.media_type, small=True)

        # Check circle (top-left)
        if node.checkable:
            cr = self._check_rect(r)
            circle = QPainterPath()
            circle.addEllipse(QRectF(cr))
            if node.checked:
                painter.fillPath(circle, QColor(T.ACCENT))
                painter.setPen(QPen(QColor("white"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                x, y, w = cr.x(), cr.y(), cr.width()
                painter.drawPolyline(QPolygonF([
                    QPointF(x + w * 0.28, y + w * 0.52), QPointF(x + w * 0.44, y + w * 0.68), QPointF(x + w * 0.73, y + w * 0.34),
                ]))
            else:
                painter.fillPath(circle, QColor(0, 0, 0, 90))
                painter.setPen(QPen(QColor("white"), 1.6))
                painter.drawEllipse(QRectF(cr).adjusted(0.8, 0.8, -0.8, -0.8))

        # Name + status
        text_x = r.x() + 10
        text_w = r.width() - 20
        name_rect = QRect(text_x, box.bottom() + 8, text_w, 18)
        f = QFont()
        f.setPixelSize(12)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(T.TEXT_PRIMARY if node.is_new else T.TEXT_SECONDARY))
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(node.file.name, Qt.ElideMiddle, text_w))

        f.setBold(False)
        f.setPixelSize(11)
        painter.setFont(f)
        status_rect = QRect(text_x, name_rect.bottom() + 2, text_w, 16)
        painter.setPen(QColor(_status_color(node.status_color)))
        painter.drawText(status_rect, Qt.AlignLeft | Qt.AlignVCenter, node.status)
        painter.setPen(QColor(T.TEXT_SECONDARY))
        painter.drawText(status_rect, Qt.AlignRight | Qt.AlignVCenter, f"{node.file.size_mb:.0f} MB")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        # Clicking the check circle toggles without changing the selection
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            node: _Node = index.data(NODE_ROLE)
            if node is not None and node.checkable:
                r = option.rect.adjusted(6, 4, -6, -4)
                hit = self._check_rect(r).adjusted(-6, -6, 6, 6)
                if hit.contains(event.position().toPoint()):
                    if event.type() == QEvent.MouseButtonRelease:
                        model.setData(index, Qt.Unchecked if node.checked else Qt.Checked, Qt.CheckStateRole)
                    return True
        return super().editorEvent(event, model, option, index)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class FileTable(QWidget):
    selection_changed = Signal(int, object)  # checked count, checked bytes
    view_mode_changed = Signal(str)         # "list" | "grid"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loader = ThumbnailLoader(self)
        self._model = FileModel(self._loader, self)
        self._proxy = FileFilter(self)
        self._proxy.setSourceModel(self._model)
        self._model.selection_changed.connect(self._on_selection_changed)
        self._view_mode = "list"
        self._summary_text = ""
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Summary bar: totals (left) · selection (right)
        self._summary_bar = QWidget()
        self._summary_bar.setFixedHeight(36)
        sb = QHBoxLayout(self._summary_bar)
        sb.setContentsMargins(16, 0, 16, 0)
        self._summary = QLabel("")
        sf = QFont()
        sf.setPixelSize(12)
        self._summary.setFont(sf)
        sb.addWidget(self._summary)
        sb.addStretch()
        self._selection_lbl = QLabel("")
        self_font = QFont()
        self_font.setPixelSize(12)
        self_font.setBold(True)
        self._selection_lbl.setFont(self_font)
        sb.addWidget(self._selection_lbl)
        sb.addSpacing(10)
        self._select_all_btn = self._chip("Select All")
        self._select_all_btn.clicked.connect(lambda: self._check_visible(True))
        self._select_none_btn = self._chip("None")
        self._select_none_btn.clicked.connect(lambda: self._check_visible(False))
        for btn in (self._select_all_btn, self._select_none_btn):
            btn.setFixedHeight(24)
            btn.setVisible(False)   # shown once files are loaded
            sb.addWidget(btn)
        layout.addWidget(self._summary_bar)

        # Scan info bar — detected camera profile + per-root file counts
        self._scan_info_bar = QWidget()
        self._scan_info_bar.setFixedHeight(28)
        si = QHBoxLayout(self._scan_info_bar)
        si.setContentsMargins(16, 0, 16, 0)
        self._scan_info_lbl = QLabel("")
        sif = QFont()
        sif.setPixelSize(11)
        self._scan_info_lbl.setFont(sif)
        si.addWidget(self._scan_info_lbl)
        si.addStretch()
        self._scan_info_bar.setVisible(False)
        layout.addWidget(self._scan_info_bar)

        # Filter bar
        self._filter_bar = QWidget()
        self._filter_bar.setFixedHeight(44)
        fb = QHBoxLayout(self._filter_bar)
        fb.setContentsMargins(14, 0, 14, 0)
        fb.setSpacing(6)

        self._new_only_btn = self._chip("New only", checkable=True)
        self._new_only_btn.toggled.connect(self._apply_filters)
        fb.addWidget(self._new_only_btn)
        fb.addSpacing(8)

        self._kind_group = QButtonGroup(self)
        self._kind_group.setExclusive(True)
        self._kind_buttons: dict[str, QPushButton] = {}
        for label in _KIND_FILTERS:
            btn = self._chip(label, checkable=True)
            self._kind_group.addButton(btn)
            self._kind_buttons[label] = btn
            fb.addWidget(btn)
        self._kind_buttons["All"].setChecked(True)
        self._kind_group.buttonToggled.connect(lambda *_: self._apply_filters())
        fb.addSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search files")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(28)
        self._search.setMinimumWidth(130)
        self._search.setMaximumWidth(240)
        self._search.textChanged.connect(lambda *_: self._search_timer.start())
        fb.addWidget(self._search, stretch=1)
        fb.addStretch()


        self._seg = QWidget()
        self._seg.setObjectName("segContainer")
        self._seg.setFixedHeight(28)
        seg = QHBoxLayout(self._seg)
        seg.setContentsMargins(2, 2, 2, 2)
        seg.setSpacing(0)
        self._view_group = QButtonGroup(self)
        self._list_btn = QPushButton("List")
        self._grid_btn = QPushButton("Grid")
        for btn, mode in ((self._list_btn, "list"), (self._grid_btn, "grid")):
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda _c=False, m=mode: self.set_view_mode(m))
            self._view_group.addButton(btn)
            seg.addWidget(btn)
        self._list_btn.setChecked(True)
        fb.addWidget(self._seg)
        layout.addWidget(self._filter_bar)

        div = QWidget()
        div.setFixedHeight(1)
        self._summary_div = div
        layout.addWidget(div)

        # Empty state
        self._empty = QWidget()
        el = QVBoxLayout(self._empty)
        el.setAlignment(Qt.AlignCenter)
        self._empty_title = QLabel("No files scanned yet")
        etf = QFont()
        etf.setPixelSize(15)
        etf.setBold(True)
        self._empty_title.setFont(etf)
        self._empty_title.setAlignment(Qt.AlignCenter)
        self._empty_sub = QLabel("Insert a camera card — it will be scanned automatically.\n"
                                 "Or select a card in the sidebar and click Scan Card.")
        self._empty_sub.setAlignment(Qt.AlignCenter)
        self._empty_sub.setWordWrap(True)
        el.addStretch()
        el.addWidget(self._empty_title)
        el.addSpacing(6)
        el.addWidget(self._empty_sub)
        el.addStretch()
        layout.addWidget(self._empty, stretch=1)

        # Views
        self._views = QStackedWidget()

        self._tree = QTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setUniformRowHeights(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(14)
        self._tree.setIconSize(_LIST_THUMB)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setAlternatingRowColors(False)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(COL_TIME, Qt.AscendingOrder)
        hdr = self._tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_KIND, QHeaderView.Fixed)
        for col, width in ((COL_KIND, 76), (COL_TIME, 96), (COL_SIZE, 92), (COL_STATUS, 150)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            self._tree.setColumnWidth(col, width)
        self._badge_delegate = _BadgeDelegate(self._tree)
        self._tree.setItemDelegateForColumn(COL_KIND, self._badge_delegate)
        self._tree.installEventFilter(self)
        self._views.addWidget(self._tree)

        self._grid = QListView()
        self._grid.setModel(self._proxy)
        self._grid.setViewMode(QListView.IconMode)
        self._grid.setResizeMode(QListView.Adjust)
        self._grid.setMovement(QListView.Static)
        self._grid.setUniformItemSizes(True)
        self._grid.setGridSize(_GRID_CELL)
        # A permanent scrollbar keeps the viewport width stable, so fitting
        # columns can't flip-flop as the scrollbar appears and disappears.
        self._grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._grid.viewport().installEventFilter(self)
        self._grid.setSpacing(0)
        self._grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._grid.setMouseTracking(True)
        self._grid_delegate = _GridDelegate(self._grid)
        self._grid.setItemDelegate(self._grid_delegate)
        self._grid.installEventFilter(self)
        self._views.addWidget(self._grid)

        # Group rows span all columns; keep that across resets/sorts/filters.
        # Coalesced: one pass per event-loop turn however many signals fire.
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(0)
        self._layout_timer.timeout.connect(self._after_layout)
        for sig in (self._proxy.modelReset, self._proxy.layoutChanged, self._proxy.rowsInserted):
            sig.connect(self._layout_timer.start)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._apply_filters)

        self._views.hide()
        self._filter_bar.hide()
        layout.addWidget(self._views, stretch=1)
        self.apply_theme()

    def _chip(self, text: str, *, checkable: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(checkable)
        btn.setFixedHeight(26)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def apply_theme(self):
        bar = f"background: {T.BG_TABLE_HDR}; border-bottom: 0px;"
        self._summary_bar.setStyleSheet(
            f"QWidget {{ background: {T.BG_TABLE_HDR}; }}" + _chip_style()
        )
        self._scan_info_bar.setStyleSheet(bar)
        self._filter_bar.setStyleSheet(
            f"QWidget {{ background: {T.BG_TABLE_HDR}; }}"
            + _chip_style()
            + T.INPUT_STYLE
            + " QLineEdit { min-height: 0; padding: 0 8px; font-size: 12px; border-radius: 13px; }"
            + T.SEGMENT_STYLE.replace("min-width: 82px;", "min-width: 48px;").replace("font-size: 13px;", "font-size: 12px;")
        )
        self._scan_info_lbl.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent;")
        self._summary_div.setStyleSheet(f"background: {T.DIVIDER};")
        self._summary.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
        self._selection_lbl.setStyleSheet(f"color: {T.ACCENT}; background: transparent;")
        self._empty.setStyleSheet(f"background: {T.BG_TABLE};")
        self._empty_title.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        self._empty_sub.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 13px; background: transparent;")
        style = T.TABLE_STYLE.replace("QTableWidget", "QTreeView")
        # Item colors come from the model (status colors); a stylesheet
        # `color` on ::item would override them.
        style = re.sub(r"(QTreeView::item(?::selected)?\s*\{[^}]*?)color:[^;]+;", r"\1", style)
        self._tree.setStyleSheet(
            style
            + f" QTreeView::branch {{ background: transparent; }}"
            + f" QTreeView::item {{ padding: 2px 8px; }}"
            + indicator_style(
                "QTreeView", accent=T.ACCENT, border=T.TEXT_MUTED,
                disabled_bg=T.BG_TABLE_ALT, disabled_border=T.BORDER,
            )
        )
        self._grid.setStyleSheet(
            f"QListView {{ background: {T.BG_TABLE}; border: none; padding: 8px; }}"
            + style[style.index("QScrollBar:vertical"):]
        )
        _placeholder_cache.clear()
        self._model._emit_all_changed()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, files: list[MediaFile], new_set: set[str] | None = None, *, keep_selection: bool = False):
        """
        Show scanned files. keep_selection=True keeps the user's unchecked
        files unchecked (used when re-planning after a destination change).
        """
        self._model.load(files, new_set, keep_selection=keep_selection)
        # Dynamic sorting is off (status updates shouldn't reshuffle rows),
        # so re-apply the current sort after replacing the data.
        if self._view_mode == "list":
            hdr = self._tree.header()
            self._proxy.sort(hdr.sortIndicatorSection(), hdr.sortIndicatorOrder())
        else:
            self._proxy.sort(COL_TIME, Qt.AscendingOrder)
        new_count = sum(1 for f in files if new_set is None or str(f.path) in new_set)
        total = sum(f.size_bytes for f in files)
        self._summary_text = (
            f"{len(files)} files  ·  {format_size(total)}  ·  "
            f"{new_count} new  ·  {len(files) - new_count} already imported"
        )
        self._summary.setText(self._summary_text)
        self._empty.hide()
        self._filter_bar.show()
        self._views.show()
        self._select_all_btn.show()
        self._select_none_btn.show()
        self._layout_timer.start()

    def clear(self):
        self._model.clear()
        self._views.hide()
        self._filter_bar.hide()
        self._select_all_btn.hide()
        self._select_none_btn.hide()
        self._empty.show()
        self._summary.setText("")
        self._selection_lbl.setText("")
        self._scan_info_bar.setVisible(False)

    def set_scan_info(self, profile_name: str, roots_scanned: dict[Path, int]) -> None:
        """Show the detected camera profile and per-folder file counts."""
        if not profile_name and not roots_scanned:
            self._scan_info_bar.setVisible(False)
            return
        parts = [f"Camera: {profile_name}"] if profile_name else []
        for root, count in roots_scanned.items():
            parts.append(f"{'/'.join(root.parts[-2:])} → {count} files")
        self._scan_info_lbl.setText("   ·   ".join(parts))
        self._scan_info_bar.setVisible(True)

    def checked_files(self) -> list[MediaFile]:
        return self._model.checked_files()

    def selection_summary(self) -> tuple[int, int]:
        return self._model.selection_summary()

    def set_locked(self, locked: bool):
        """Disable check boxes and selection buttons while importing."""
        self._model.set_locked(locked)
        self._select_all_btn.setEnabled(not locked)
        self._select_none_btn.setEnabled(not locked)

    def view_mode(self) -> str:
        return self._view_mode

    def set_view_mode(self, mode: str):
        if mode not in ("list", "grid"):
            return
        self._list_btn.setChecked(mode == "list")
        self._grid_btn.setChecked(mode == "grid")
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self._model.set_grouped(mode == "list")
        self._views.setCurrentWidget(self._tree if mode == "list" else self._grid)
        if mode == "grid":
            self._proxy.sort(COL_TIME, Qt.AscendingOrder)
            self._fit_grid()
        self._layout_timer.start()
        self.view_mode_changed.emit(mode)

    # Status updates — called from the importer's progress signals

    def mark_in_progress(self, filename: str):
        node = self._model.set_status(filename, "In Progress…", "warning")
        if node is not None:
            proxy_idx = self._proxy.mapFromSource(self._model.index_for_node(node))
            if proxy_idx.isValid():
                self._active_view().scrollTo(proxy_idx)

    def mark_copied(self, filename: str):
        self._model.set_status(filename, "Copied ✓", "success")

    def mark_verifying(self, filename: str):
        self._model.set_status(filename, "Verifying…", "warning")

    def mark_verified(self, filename: str):
        self._model.set_status(filename, "Verified ✓", "success")

    def mark_verify_failed(self, filename: str):
        self._model.set_status(filename, "Verify Failed ✗", "danger")

    def mark_conflict(self, filename: str):
        self._model.set_status(filename, "Conflict ⚠", "conflict")

    def mark_failed(self, filename: str):
        self._model.set_status(filename, "Failed ✗", "danger")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _active_view(self) -> QAbstractItemView:
        return self._tree if self._view_mode == "list" else self._grid

    def _after_layout(self, *_):
        if self._view_mode != "list":
            return
        root = QModelIndex()
        for r in range(self._proxy.rowCount(root)):
            self._tree.setFirstColumnSpanned(r, root, True)
        self._tree.expandAll()

    def _apply_filters(self, *_):
        kind_label = next((k for k, b in self._kind_buttons.items() if b.isChecked()), "All")
        self._proxy.set_filters(
            kinds=_KIND_FILTERS[kind_label],
            new_only=self._new_only_btn.isChecked(),
            text=self._search.text(),
        )
        self._layout_timer.start()
        self._update_selection_label(*self._model.selection_summary())

    def _check_visible(self, checked: bool):
        self._model.set_checked(self._proxy.visible_nodes(), checked)

    def _on_selection_changed(self, count: int, size: int):
        self._update_selection_label(count, size)
        self.selection_changed.emit(count, size)

    def _update_selection_label(self, count: int, size: int):
        if not self._model.has_files():
            self._selection_lbl.setText("")
            return
        text = f"{count} selected  ·  {format_size(size)}" if count else "Nothing selected"
        if self._proxy.is_filtered():
            text = f"{self._proxy_visible_count()} shown  ·  " + text
        self._selection_lbl.setText(text)

    def _proxy_visible_count(self) -> int:
        return len(self._proxy.visible_nodes())

    def _fit_grid(self):
        """Size grid cells so whole columns exactly fill the available width."""
        # Qt's icon flow wraps when cells exactly fill the row — keep 4px slack
        width = self._grid.viewport().width() - 4
        if width <= 0:
            return
        columns = max(1, width // _GRID_MIN_W)
        cell_w = width // columns
        thumb_h = round((cell_w - 12 - 8) * 2 / 3)   # card margins, then 3:2
        size = QSize(cell_w, thumb_h + 8 + _GRID_TEXT_H)
        if size != self._grid.gridSize():
            self._grid.setGridSize(size)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self._grid.viewport():
            self._fit_grid()
        # Space toggles the check box of the highlighted rows/cards
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space and obj in (self._tree, self._grid):
            nodes = [
                idx.data(NODE_ROLE) for idx in obj.selectionModel().selectedIndexes()
                if idx.column() == COL_NAME
            ]
            files = [n for n in nodes if n is not None and not n.is_group and n.checkable]
            if files:
                self._model.set_checked(files, not all(n.checked for n in files))
                return True
        return super().eventFilter(obj, event)


def _chip_style() -> str:
    return f"""
        QPushButton {{
            background: {T.BG_SEGMENT}; border: none; border-radius: 12px;
            color: {T.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;
            padding: 0 12px;
        }}
        QPushButton:hover {{ color: {T.TEXT_PRIMARY}; }}
        QPushButton:checked {{ background: {T.ACCENT}; color: white; }}
        QPushButton:disabled {{ color: {T.TEXT_MUTED}; }}
    """
