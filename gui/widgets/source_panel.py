"""
Source Panel — sidebar showing connected drives.
  • Camera Cards  — SD cards (scan source)
  • Storage Drives — external HDDs/SSDs (import destination)
No internal header bar; section labels are inline.
"""

from __future__ import annotations
import logging
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea
)
from PySide6.QtCore import Signal, Qt, QTimer, QRect
from PySide6.QtGui import QFont, QPainter

from backend.utils.detector import list_drives, DriveInfo
from gui.theme import T

logger = logging.getLogger(__name__)


class ElidedLabel(QLabel):
    """QLabel that elides text with '…' when it doesn't fit."""

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = self.fontMetrics()
        elided = metrics.elidedText(self.text(), Qt.ElideRight, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        painter.drawText(QRect(0, 0, self.width(), self.height()),
                         int(self.alignment()), elided)
        painter.end()


class DriveCard(QFrame):
    clicked = Signal(object)

    def __init__(self, drive: DriveInfo, parent=None):
        super().__init__(parent)
        self.drive = drive
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(70)
        self._build()
        self._apply_style(False)

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        icon_lbl = QLabel("💾" if self.drive.is_camera_card else "💽")
        icon_lbl.setFont(QFont("Arial", 20))
        icon_lbl.setFixedWidth(30)
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        self._name_lbl = ElidedLabel(self.drive.label)
        nf = QFont()
        nf.setPixelSize(13)
        nf.setBold(True)
        self._name_lbl.setFont(nf)
        self._name_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        kind = "SD Card" if self.drive.is_camera_card else "External Drive"
        self._detail_lbl = ElidedLabel(f"{kind}  ·  {self.drive.free_gb} GB free")
        df = QFont()
        df.setPixelSize(11)
        self._detail_lbl.setFont(df)
        self._detail_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        text_col.addWidget(self._name_lbl)
        text_col.addWidget(self._detail_lbl)
        layout.addLayout(text_col)
        self._refresh_labels()

    def _refresh_labels(self):
        self._name_lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        self._detail_lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style(selected)

    def _apply_style(self, selected: bool):
        self._refresh_labels()
        if selected:
            self.setStyleSheet(f"""
                DriveCard {{
                    background: {T.BG_CARD_SEL};
                    border: 1.5px solid {T.BORDER_CARD_SEL};
                    border-radius: 10px;
                }}
                QLabel {{ background: transparent; border: none; }}
            """)
        else:
            hover_bg = "#252528" if T.dark else "#ebebf0"
            hover_border = "#3a3a3c" if T.dark else "#d1d1d6"
            self.setStyleSheet(f"""
                DriveCard {{
                    background: {T.BG_CARD};
                    border: 1px solid {T.BORDER_CARD};
                    border-radius: 10px;
                }}
                DriveCard:hover {{
                    background: {hover_bg};
                    border: 1px solid {hover_border};
                }}
                QLabel {{ background: transparent; border: none; }}
            """)

    def mousePressEvent(self, event):
        self.clicked.emit(self.drive)


class SourcePanel(QWidget):
    drive_selected = Signal(object)
    card_inserted  = Signal(object)   # a single new camera card was auto-selected
    drive_removed  = Signal(object)   # the selected drive was unplugged
    _drives_ready  = Signal(object)   # emitted from the polling thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)
        self._all_cards: list[DriveCard] = []
        self._selected_drive: DriveInfo | None = None
        self._drives: list[DriveInfo] | None = None
        self._fingerprint: tuple | None = None
        self._card_ids: set[str] = set()
        self._polling = False
        self._paused = False
        self._drives_ready.connect(self._on_drives_ready)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(3000)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Slim top bar: just a refresh button aligned right
        top_bar = QWidget()
        top_bar.setFixedHeight(44)
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(14, 0, 10, 0)

        self._section_top_lbl = QLabel("DRIVES")
        sf = QFont()
        sf.setPixelSize(10)
        sf.setBold(True)
        self._section_top_lbl.setFont(sf)
        tb_layout.addWidget(self._section_top_lbl)
        tb_layout.addStretch()

        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip("Refresh drives")
        self._refresh_btn.clicked.connect(self.refresh)
        tb_layout.addWidget(self._refresh_btn)

        self._top_bar = top_bar
        root.addWidget(top_bar)

        # Divider
        div = QWidget()
        div.setFixedHeight(1)
        self._top_div = div
        root.addWidget(div)

        # Scrollable body
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(10, 8, 10, 16)
        self._body_layout.setSpacing(4)
        self._body_layout.addStretch()

        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, stretch=1)

        self.apply_theme()
        self.refresh()

    def apply_theme(self):
        self._top_bar.setStyleSheet(
            f"QWidget {{ background: {T.BG_SIDEBAR}; }}"
            f" QLabel {{ color: {T.TEXT_MUTED}; letter-spacing: 1.5px; background: transparent; }}"
        )
        self._top_div.setStyleSheet(f"background: {T.DIVIDER};")
        self._refresh_btn.setStyleSheet(T.small_btn_style())
        self.setStyleSheet(f"SourcePanel {{ background: {T.BG_SIDEBAR}; }}")
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {T.BG_SIDEBAR}; border: none; }}"
            f" QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f" QScrollBar::handle:vertical {{ background: {T.BORDER}; border-radius: 3px; }}"
            f" QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        self._body.setStyleSheet(f"background: {T.BG_SIDEBAR};")
        if self._drives is not None:
            self._rebuild(self._drives)
        else:
            self.refresh()

    def set_paused(self, paused: bool):
        """
        Pause automatic polling — used during imports. Querying a drive that
        is busy with a large copy (diskutil, disk_usage) is slow and only adds
        I/O load, and nothing in the sidebar needs to change mid-import.
        """
        self._paused = paused

    def _auto_refresh(self):
        if not self._paused:
            self.refresh()

    def refresh(self):
        """
        Re-detect drives on a background thread. Drive detection shells out to
        diskutil per volume and can block for seconds, so it must never run
        on the UI thread.
        """
        if self._polling:
            return
        self._polling = True

        def _worker():
            try:
                drives = list_drives()
            except Exception as e:
                logger.error("Drive detection failed: %s", e)
                drives = None
            try:
                self._drives_ready.emit(drives)
            except RuntimeError:
                pass   # panel was destroyed while polling (app quitting)

        threading.Thread(target=_worker, daemon=True, name="DrivePoll").start()

    def _on_drives_ready(self, drives: list[DriveInfo] | None):
        self._polling = False
        if drives is None:
            return
        fingerprint = tuple(
            (d.unique_id, str(d.mount_point), d.label, d.is_camera_card, d.free_gb)
            for d in drives
        )
        if fingerprint == self._fingerprint:
            return   # nothing changed — don't tear down and rebuild the cards
        self._fingerprint = fingerprint
        self._drives = drives

        ids = {d.unique_id for d in drives}
        lost = self._selected_drive
        if lost is not None and lost.unique_id not in ids:
            self._selected_drive = None
        else:
            lost = None

        cards = [d for d in drives if d.is_camera_card]
        new_cards = [d for d in cards if d.unique_id not in self._card_ids]
        self._card_ids = {d.unique_id for d in cards}

        # Exactly one camera card and it just appeared → select it for the user
        auto = None
        if len(cards) == 1 and new_cards and (
            self._selected_drive is None or not self._selected_drive.is_camera_card
        ):
            auto = cards[0]
            self._selected_drive = auto

        self._rebuild(drives)

        if lost is not None:
            self.drive_removed.emit(lost)
        if auto is not None:
            self.card_inserted.emit(auto)

    def _rebuild(self, drives: list[DriveInfo]):
        cards   = [d for d in drives if d.is_camera_card]
        storage = [d for d in drives if d.is_external_drive]

        while self._body_layout.count() > 1:
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._all_cards.clear()
        idx = 0

        self._body_layout.insertWidget(idx, self._section_label("CAMERA CARDS")); idx += 1
        if cards:
            for d in cards:
                self._body_layout.insertWidget(idx, self._make_card(d)); idx += 1
        else:
            self._body_layout.insertWidget(idx, self._empty_label("No camera card detected")); idx += 1

        self._body_layout.insertWidget(idx, self._section_label("STORAGE DRIVES")); idx += 1
        if storage:
            for d in storage:
                self._body_layout.insertWidget(idx, self._make_card(d)); idx += 1
        else:
            self._body_layout.insertWidget(idx, self._empty_label("No external drive detected")); idx += 1

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = QFont()
        f.setPixelSize(10)
        f.setBold(True)
        lbl.setFont(f)
        lbl.setStyleSheet(
            f"color: {T.TEXT_MUTED}; letter-spacing: 1.5px; "
            f"padding: 14px 4px 5px 4px; background: transparent;"
        )
        return lbl

    def _empty_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 11px; "
            f"padding: 10px 4px; background: transparent;"
        )
        lbl.setWordWrap(True)
        return lbl

    def _make_card(self, drive: DriveInfo) -> DriveCard:
        card = DriveCard(drive)
        card.clicked.connect(self._on_card_clicked)
        self._all_cards.append(card)
        if self._selected_drive and drive.unique_id == self._selected_drive.unique_id:
            card.set_selected(True)
        return card

    def _on_card_clicked(self, drive: DriveInfo):
        self._selected_drive = drive
        for card in self._all_cards:
            card.set_selected(card.drive.unique_id == drive.unique_id)
        self.drive_selected.emit(drive)

    def clear_selection(self):
        self._selected_drive = None
        for card in self._all_cards:
            card.set_selected(False)

    def selected_drive(self) -> DriveInfo | None:
        return self._selected_drive
