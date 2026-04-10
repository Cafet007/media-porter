"""
Session naming dialog — shown before import starts.

Lets the user give the session a name (client name, shoot name, etc.)
so the history panel can group and label imports meaningfully.
The name is optional; pressing Enter or clicking Import proceeds either way.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent

from gui.theme import T


class SessionNameDialog(QDialog):
    """
    Small modal that asks for a session name before import.

    Usage::

        dlg = SessionNameDialog(file_count=42, source_label="SONY_CARD", parent=self)
        if dlg.exec() == QDialog.Accepted:
            name = dlg.session_name()   # may be "" if user left it blank
    """

    def __init__(
        self,
        file_count: int,
        source_label: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Name This Import")
        self.setModal(True)
        self.setFixedWidth(460)
        self.setStyleSheet(f"QDialog {{ background: {T.BG_BASE}; }}")
        self._build(file_count, source_label)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self, file_count: int, source_label: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(0)

        # Title
        title = QLabel("Name This Import")
        tf = QFont()
        tf.setPixelSize(18)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {T.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(title)
        layout.addSpacing(6)

        # Subtitle — show what's about to be imported
        default_name = self._default_name(source_label)
        parts = [f"{file_count} file{'s' if file_count != 1 else ''}"]
        if source_label:
            parts.append(f"from {source_label}")
        subtitle = QLabel("  ·  ".join(parts))
        subtitle.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px; background: transparent;")
        layout.addWidget(subtitle)
        layout.addSpacing(22)

        # Name input
        name_lbl = QLabel("Session name  (optional)")
        name_lbl.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 12px; font-weight: 600; background: transparent;")
        layout.addWidget(name_lbl)
        layout.addSpacing(6)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(default_name)
        self._name_edit.setFixedHeight(36)
        self._name_edit.setStyleSheet(T.INPUT_STYLE + " QLineEdit { font-size: 14px; }")
        self._name_edit.returnPressed.connect(self._accept)
        layout.addWidget(self._name_edit)
        layout.addSpacing(6)

        hint = QLabel("Used to label this group in Import History. Leave blank to use the date.")
        hint.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: 11px; background: transparent;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(24)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        skip_btn = QPushButton("Skip")
        skip_btn.setFixedHeight(36)
        skip_btn.setStyleSheet(T.btn_secondary(h=36))
        skip_btn.clicked.connect(self._accept)   # proceed with empty name
        btn_row.addWidget(skip_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(36)
        cancel_btn.setStyleSheet(T.btn_secondary(h=36))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        import_btn = QPushButton("Import →")
        import_btn.setFixedHeight(36)
        import_btn.setStyleSheet(T.btn_primary(h=36))
        import_btn.setDefault(True)
        import_btn.clicked.connect(self._accept)
        btn_row.addWidget(import_btn)

        layout.addLayout(btn_row)

        self._name_edit.setFocus()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _default_name(self, source_label: str) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        if source_label:
            return f"{date_str} — {source_label}"
        return date_str

    def _accept(self):
        self.accept()

    def session_name(self) -> str:
        """Return the trimmed name the user entered, or "" if blank."""
        return self._name_edit.text().strip()
