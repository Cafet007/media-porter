"""
Summary Panel — shown in the centre area when an import finishes.

  ┌──────────────────────────────────────────┐
  │                  ( ✓ )                   │
  │             Import Complete              │
  │  412 files · 38.2 GB · all verified · 6m │
  │                                          │
  │   [412 copied] [412 verified] [20 skip]  │
  │                                          │
  │   Problems (list, only when any)         │
  │                                          │
  │  [Show in Finder] [Eject Card] [Report]  │
  │        [Retry 3 Failed]  [View Files]    │
  └──────────────────────────────────────────┘
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from backend.core.messages import describe_error, format_duration, format_size
from gui.theme import T


def _reveal_label() -> str:
    if sys.platform == "darwin":
        return "Show in Finder"
    if sys.platform == "win32":
        return "Show in Explorer"
    return "Open Folder"


class _Stat(QFrame):
    """A number over a label, e.g. 412 / Copied."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stat")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(2)
        self._value = QLabel("0")
        vf = QFont()
        vf.setPixelSize(22)
        vf.setBold(True)
        self._value.setFont(vf)
        self._value.setAlignment(Qt.AlignCenter)
        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value)
        layout.addWidget(self._label)
        self._color = T.TEXT_PRIMARY

    def set_value(self, value: int, color: str | None = None):
        self._value.setText(str(value))
        self._color = color or T.TEXT_PRIMARY
        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(
            f"QFrame#stat {{ background: {T.BG_CARD}; border: 1px solid {T.BORDER_CARD};"
            f" border-radius: 10px; }}"
        )
        self._value.setStyleSheet(f"color: {self._color}; background: transparent;")
        self._label.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px; background: transparent;")


class SummaryPanel(QWidget):
    reveal_requested  = Signal()
    eject_requested   = Signal()
    report_requested  = Signal()
    retry_requested   = Signal()
    files_requested   = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tone = T.SUCCESS
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        column = QWidget()
        column.setMaximumWidth(620)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._icon = QLabel("✓")
        self._icon.setFixedSize(64, 64)
        self._icon.setAlignment(Qt.AlignCenter)
        icf = QFont()
        icf.setPixelSize(30)
        icf.setBold(True)
        self._icon.setFont(icf)
        col.addWidget(self._icon, alignment=Qt.AlignHCenter)
        col.addSpacing(16)

        self._title = QLabel("Import Complete")
        tf = QFont()
        tf.setPixelSize(22)
        tf.setBold(True)
        self._title.setFont(tf)
        self._title.setAlignment(Qt.AlignCenter)
        col.addWidget(self._title)
        col.addSpacing(6)

        self._subtitle = QLabel("")
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setWordWrap(True)
        col.addWidget(self._subtitle)
        col.addSpacing(22)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self._stat_copied   = _Stat("Copied")
        self._stat_verified = _Stat("Verified")
        self._stat_skipped  = _Stat("Already there")
        self._stat_problems = _Stat("Problems")
        for s in (self._stat_copied, self._stat_verified, self._stat_skipped, self._stat_problems):
            stats.addWidget(s, stretch=1)
        col.addLayout(stats)
        col.addSpacing(18)

        self._problems_title = QLabel("NEEDS ATTENTION")
        pf = QFont()
        pf.setPixelSize(10)
        pf.setBold(True)
        self._problems_title.setFont(pf)
        col.addWidget(self._problems_title)
        col.addSpacing(6)

        self._problems = QListWidget()
        self._problems.setMaximumHeight(160)
        self._problems.setSelectionMode(QListWidget.NoSelection)
        self._problems.setFocusPolicy(Qt.NoFocus)
        self._problems.setWordWrap(True)
        self._problems.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        col.addWidget(self._problems)
        col.addSpacing(22)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addStretch()
        self._reveal_btn = QPushButton(_reveal_label())
        self._reveal_btn.clicked.connect(self.reveal_requested)
        self._eject_btn = QPushButton("Eject Card")
        self._eject_btn.clicked.connect(self.eject_requested)
        self._report_btn = QPushButton("Save Report…")
        self._report_btn.clicked.connect(self.report_requested)
        for b in (self._reveal_btn, self._eject_btn, self._report_btn):
            b.setFixedHeight(38)
            row1.addWidget(b)
        row1.addStretch()
        col.addLayout(row1)
        col.addSpacing(10)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addStretch()
        self._retry_btn = QPushButton("Retry Failed")
        self._retry_btn.clicked.connect(self.retry_requested)
        self._files_btn = QPushButton("View Files")
        self._files_btn.clicked.connect(self.files_requested)
        for b in (self._retry_btn, self._files_btn):
            b.setFixedHeight(32)
            row2.addWidget(b)
        row2.addStretch()
        col.addLayout(row2)

        outer.addWidget(column, alignment=Qt.AlignHCenter)
        outer.addStretch(2)
        self.apply_theme()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_result(self, result, *, cancelled: bool, elapsed_sec: float, can_eject: bool):
        problems: list[tuple[str, str]] = []
        for f, err in result.failed:
            problems.append((f.name, describe_error(err)))
        for f in result.verify_failed:
            problems.append((f.name, "Copy didn't match the original — the file on the drive may be damaged."))
        for f in result.conflicts:
            problems.append((f.name, describe_error("DESTINATION EXISTS")))

        copied_bytes = sum(f.size_bytes for f, _ in result.copied)
        n = result.total_copied

        if cancelled:
            self._tone, icon, title = T.WARNING, "■", "Import Cancelled"
        elif problems:
            self._tone, icon, title = T.WARNING, "!", "Import Finished with Problems"
        elif n == 0:
            self._tone, icon, title = T.SUCCESS, "✓", "Nothing New to Import"
        else:
            self._tone, icon, title = T.SUCCESS, "✓", "Import Complete"
        self._icon.setText(icon)
        self._title.setText(title)

        parts = [f"{n} file{'s' if n != 1 else ''}", format_size(copied_bytes)]
        if n and result.total_verified == n:
            parts.append("all verified")
        if elapsed_sec >= 1:
            parts.append(format_duration(elapsed_sec))
        self._subtitle.setText("  ·  ".join(parts))

        self._stat_copied.set_value(n)
        self._stat_verified.set_value(
            result.total_verified,
            T.SUCCESS if n and result.total_verified == n else None,
        )
        self._stat_skipped.set_value(result.total_skipped)
        self._stat_problems.set_value(len(problems), T.DANGER if problems else None)

        self._problems.clear()
        for name, reason in problems:
            item = QListWidgetItem(f"{name}  —  {reason}")
            item.setForeground(QColor(T.TEXT_PRIMARY))
            self._problems.addItem(item)
        self._problems_title.setVisible(bool(problems))
        self._problems.setVisible(bool(problems))

        failed = result.total_failed
        self._retry_btn.setText(f"Retry {failed} Failed" if failed else "Retry Failed")
        self._retry_btn.setVisible(failed > 0)
        self._reveal_btn.setEnabled(n > 0)
        self.set_eject_state("ready" if can_eject else "unavailable")
        self.apply_theme()

    def set_eject_state(self, state: str):
        """state: 'ready' | 'busy' | 'done' | 'unavailable'."""
        text = {
            "ready": "Eject Card", "busy": "Ejecting…",
            "done": "Card Ejected ✓", "unavailable": "Eject Card",
        }[state]
        self._eject_btn.setText(text)
        self._eject_btn.setEnabled(state == "ready")

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def apply_theme(self):
        self.setStyleSheet(f"SummaryPanel {{ background: {T.BG_TABLE}; }}")
        self._icon.setStyleSheet(
            f"background: {self._tone}; color: white; border-radius: 32px;"
        )
        self._title.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        self._subtitle.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 14px; background: transparent;")
        self._problems_title.setStyleSheet(
            f"color: {T.TEXT_MUTED}; letter-spacing: 1.5px; background: transparent;"
        )
        self._problems.setStyleSheet(
            f"QListWidget {{ background: {T.BG_CARD}; border: 1px solid {T.BORDER_CARD};"
            f" border-radius: 8px; padding: 4px; font-size: 12px; color: {T.TEXT_PRIMARY}; }}"
            f" QListWidget::item {{ padding: 4px 6px; }}"
        )
        for s in (self._stat_copied, self._stat_verified, self._stat_skipped, self._stat_problems):
            s.apply_theme()
        self._reveal_btn.setStyleSheet(T.btn_primary(h=38))
        self._eject_btn.setStyleSheet(T.btn_secondary(h=38))
        self._report_btn.setStyleSheet(T.btn_secondary(h=38))
        self._retry_btn.setStyleSheet(T.btn_danger(h=32))
        self._files_btn.setStyleSheet(T.small_btn_style())
