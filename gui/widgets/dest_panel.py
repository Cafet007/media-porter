"""
Destination Panel — lets user set photo_base and video_base paths.
"""

from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QFrame
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from pathlib import Path

from backend.core.rules import DestinationConfig

logger = logging.getLogger(__name__)


class PathRow(QWidget):
    """A labeled path picker row."""

    changed = Signal(str)  # emits new path string

    def __init__(self, label: str, icon: str, default: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl = QLabel(f"{icon}  {label}")
        lbl.setFixedWidth(80)
        lbl.setFont(QFont("Arial", 12))
        lbl.setStyleSheet("color: #aaa;")
        layout.addWidget(lbl)

        self._edit = QLineEdit(default)
        self._edit.setStyleSheet("""
            QLineEdit {
                background: #2a2a2a; border: 1px solid #3a3a3a;
                border-radius: 6px; padding: 6px 10px;
                color: #eee; font-size: 12px;
            }
            QLineEdit:focus { border: 1px solid #4a9eff; }
        """)
        self._edit.textChanged.connect(self.changed)
        layout.addWidget(self._edit, stretch=1)

        browse = QPushButton("…")
        browse.setFixedSize(32, 32)
        browse.setStyleSheet("""
            QPushButton { background: #333; border: none; border-radius: 6px;
                          color: #aaa; font-size: 16px; }
            QPushButton:hover { background: #444; color: white; }
        """)
        browse.clicked.connect(self._browse)
        layout.addWidget(browse)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", self._edit.text())
        if path:
            self._edit.setText(path)

    def path(self) -> Path:
        return Path(self._edit.text())

    def set_path(self, path: str):
        self._edit.setText(path)


class DestPanel(QWidget):
    """
    Right-side panel for configuring destination folders.
    """

    config_changed = Signal(object)  # emits DestinationConfig

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(320)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background: #1a1a1a; border-bottom: 1px solid #333;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)
        title = QLabel("DESTINATION")
        title.setFont(QFont("Arial", 11, QFont.Bold))
        title.setStyleSheet("color: #888; letter-spacing: 1px;")
        h_layout.addWidget(title)
        layout.addWidget(header)

        # Body
        body = QWidget()
        body.setStyleSheet("background: #1a1a1a;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.setSpacing(16)

        # External drive root (auto-filled when drive selected)
        drive_label = QLabel("External Drive")
        drive_label.setFont(QFont("Arial", 11, QFont.Bold))
        drive_label.setStyleSheet("color: #ccc;")
        body_layout.addWidget(drive_label)

        self._photo_row = PathRow("Photos", "📷")
        self._photo_row.changed.connect(self._emit_config)
        body_layout.addWidget(self._photo_row)

        self._video_row = PathRow("Videos", "🎬")
        self._video_row.changed.connect(self._emit_config)
        body_layout.addWidget(self._video_row)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #333;")
        body_layout.addWidget(div)

        # Structure preview
        preview_label = QLabel("Folder structure:")
        preview_label.setFont(QFont("Arial", 11, QFont.Bold))
        preview_label.setStyleSheet("color: #ccc;")
        body_layout.addWidget(preview_label)

        self._preview = QLabel(self._structure_text())
        self._preview.setFont(QFont("Menlo, Courier", 11))
        self._preview.setStyleSheet("color: #666; line-height: 1.6;")
        self._preview.setWordWrap(True)
        body_layout.addWidget(self._preview)

        body_layout.addStretch()
        layout.addWidget(body, stretch=1)

    def _structure_text(self) -> str:
        return (
            "Photos/\n"
            "  RAW/\n"
            "    2026-03-24/\n"
            "  JPG/\n"
            "    2026-03-24/\n\n"
            "Footage/\n"
            "  2026-03-24/"
        )

    def set_paths(self, photo: str, video: str):
        """Restore saved paths directly (e.g. from config file)."""
        self._photo_row.set_path(photo)
        self._video_row.set_path(video)
        self._emit_config()

    def set_drive_root(self, root: Path):
        """Auto-fill paths when user selects an external drive."""
        logger.info("Destination auto-filled from drive root: %s", root)
        self._photo_row.set_path(str(root / "Photography"))
        self._video_row.set_path(str(root / "Footage"))
        self._emit_config()

    def _emit_config(self, *_):
        self._preview.setText(self._structure_text())
        self.config_changed.emit(self.config())

    def config(self) -> DestinationConfig:
        return DestinationConfig(
            photo_base=self._photo_row.path(),
            video_base=self._video_row.path(),
        )
