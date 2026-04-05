"""
Settings Panel — folder naming rule templates + live preview.
Opens as a dialog from the main window's settings button.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QGridLayout, QFrame, QScrollArea
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont

from gui.theme import T


class TemplateRow(QWidget):
    """One editable template row with a live preview label."""

    changed = Signal()

    def __init__(self, label: str, key: str, template: str, parent=None):
        super().__init__(parent)
        self._key = key
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._lbl = QLabel(label)
        lbl_font = QFont()
        lbl_font.setPixelSize(13)
        lbl_font.setBold(True)
        self._lbl.setFont(lbl_font)
        layout.addWidget(self._lbl)

        self._edit = QLineEdit(template)
        self._edit.setMinimumHeight(36)
        self._edit.textChanged.connect(self._update_preview)
        self._edit.textChanged.connect(self.changed)
        layout.addWidget(self._edit)

        self._preview = QLabel()
        preview_font = QFont("Menlo, Courier New, monospace", 11)
        self._preview.setFont(preview_font)
        layout.addWidget(self._preview)

        self._apply_styles()
        self._update_preview()

    def _apply_styles(self):
        self._lbl.setStyleSheet(f"color: {T.TEXT_PRIMARY};")
        self._edit.setStyleSheet(
            T.INPUT_STYLE +
            " QLineEdit { font-family: 'Menlo', 'Courier New', monospace; font-size: 13px; min-height: 36px; }"
        )

    def _update_preview(self):
        from backend.core.rules import preview_template
        try:
            result = preview_template(self._edit.text(), self._key)
            self._preview.setText(f"  → {result}")
            self._preview.setStyleSheet(f"color: {T.ACCENT}; padding-left: 2px;")
        except Exception as e:
            self._preview.setText(f"  ⚠ {e}")
            self._preview.setStyleSheet(f"color: {T.DANGER}; padding-left: 2px;")

    def template(self) -> str:
        return self._edit.text().strip()

    def set_template(self, t: str):
        self._edit.setText(t)


class SettingsDialog(QDialog):
    """Modal dialog for editing folder naming rule templates."""

    rules_saved = Signal(dict)

    def __init__(self, rules: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings — Folder Naming Rules")
        self.setMinimumWidth(720)
        self.resize(760, 760)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_BASE}; }}"
            f" QLabel {{ background: transparent; }}"
        )
        self._build(rules)

    def _build(self, rules: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(0)

        # Title
        title = QLabel("Folder Naming Rules")
        title_font = QFont()
        title_font.setPixelSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {T.TEXT_PRIMARY};")
        layout.addWidget(title)
        layout.addSpacing(6)

        subtitle = QLabel("Templates control how imported files are organized within your destination folders.")
        subtitle.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 13px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(24)

        # Template rows
        templates_box = QWidget()
        templates_box.setObjectName("templatesBox")
        templates_box.setStyleSheet(
            f"QWidget#templatesBox {{ background: {T.BG_PANEL}; border: 1px solid {T.BORDER}; border-radius: 12px; }}"
        )
        templates_layout = QVBoxLayout(templates_box)
        templates_layout.setContentsMargins(20, 20, 20, 20)
        templates_layout.setSpacing(20)

        self._photo_row = TemplateRow("Photos  (.jpg .heic .png)", "photo", rules.get("photo", ""))
        self._raw_row   = TemplateRow("RAW  (.arw .cr3 .nef .dng …)", "raw",   rules.get("raw",   ""))
        self._video_row = TemplateRow("Videos  (.mp4 .mov .mts …)", "video", rules.get("video", ""))

        templates_layout.addWidget(self._photo_row)
        templates_layout.addWidget(self._build_divider())
        templates_layout.addWidget(self._raw_row)
        templates_layout.addWidget(self._build_divider())
        templates_layout.addWidget(self._video_row)

        layout.addWidget(templates_box)
        layout.addSpacing(16)

        # Variable reference
        layout.addWidget(self._build_variable_ref())
        layout.addSpacing(20)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setStyleSheet(T.btn_secondary(h=36))
        reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(T.btn_secondary(h=36))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(T.btn_primary(h=36))
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _build_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {T.DIVIDER}; background: transparent;")
        return line

    def _build_variable_ref(self) -> QWidget:
        from backend.core.rules import TEMPLATE_VARIABLES

        box = QWidget()
        box.setObjectName("varRefBox")
        box.setStyleSheet(
            f"QWidget#varRefBox {{ background: {T.BG_PANEL}; border: 1px solid {T.BORDER}; border-radius: 12px; }}"
        )
        inner = QVBoxLayout(box)
        inner.setContentsMargins(20, 16, 20, 16)
        inner.setSpacing(10)

        hdr = QLabel("Available Variables")
        hdr_font = QFont()
        hdr_font.setPixelSize(12)
        hdr_font.setBold(True)
        hdr.setFont(hdr_font)
        hdr.setStyleSheet(f"color: {T.TEXT_MUTED}; letter-spacing: 1px; text-transform: uppercase;")
        inner.addWidget(hdr)

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnMinimumWidth(1, 100)

        for row, (var, example, desc) in enumerate(TEMPLATE_VARIABLES):
            v = QLabel(var)
            v.setFont(QFont("Menlo, Courier New, monospace", 11))
            v.setStyleSheet(f"color: {T.ACCENT};")

            e = QLabel(example)
            e.setFont(QFont("Menlo, Courier New, monospace", 11))
            e.setStyleSheet(f"color: {T.SUCCESS};")

            d = QLabel(desc)
            d.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 12px;")

            grid.addWidget(v, row, 0)
            grid.addWidget(e, row, 1)
            grid.addWidget(d, row, 2)

        inner.addLayout(grid)
        return box

    def _reset(self):
        from backend.core.rules import DEFAULT_TEMPLATES
        self._photo_row.set_template(DEFAULT_TEMPLATES["photo"])
        self._raw_row.set_template(DEFAULT_TEMPLATES["raw"])
        self._video_row.set_template(DEFAULT_TEMPLATES["video"])

    def _save(self):
        from backend.utils.config import save_rules
        rules = {
            "photo": self._photo_row.template(),
            "raw":   self._raw_row.template(),
            "video": self._video_row.template(),
        }
        save_rules(rules)
        self.rules_saved.emit(rules)
        self.accept()
