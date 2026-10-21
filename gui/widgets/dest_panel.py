"""
Destination Panel — right sidebar for setting photo_base and video_base paths.
No internal header bar; uses an inline section title.
"""

from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QFrame
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from pathlib import Path

from backend.core.models import MediaFile, MediaType
from backend.core.rules import DestinationConfig, DEFAULT_TEMPLATES, preview_template, resolve_template
from gui.theme import T

logger = logging.getLogger(__name__)


class PathRow(QWidget):
    changed = Signal(str)

    def __init__(self, label: str, icon: str, default: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self._lbl = QLabel(f"{icon}  {label}")
        lf = QFont()
        lf.setPixelSize(12)
        lf.setBold(True)
        self._lbl.setFont(lf)
        layout.addWidget(self._lbl)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._edit = QLineEdit(default)
        self._edit.textChanged.connect(self.changed)
        row.addWidget(self._edit, stretch=1)

        self._browse = QPushButton("…")
        self._browse.setFixedSize(34, 34)
        self._browse.clicked.connect(self._browse_dir)
        row.addWidget(self._browse)

        layout.addLayout(row)
        self.apply_theme()

    def apply_theme(self):
        self._lbl.setStyleSheet(f"color: {T.TEXT_SECONDARY}; background: transparent;")
        self._edit.setStyleSheet(T.INPUT_STYLE)
        self._browse.setStyleSheet(T.small_btn_style())

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", self._edit.text())
        if path:
            self._edit.setText(path)

    def path(self) -> Path:
        return Path(self._edit.text())

    def set_path(self, path: str):
        self._edit.setText(path)


class DestPanel(QWidget):
    config_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)
        self._templates: dict = dict(DEFAULT_TEMPLATES)
        # One real scanned file per kind, so the preview shows actual dates/names
        self._samples: dict[str, MediaFile] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Slim top bar matching SourcePanel
        top_bar = QWidget()
        top_bar.setFixedHeight(44)
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(14, 0, 14, 0)

        self._title_lbl = QLabel("DESTINATION")
        tf = QFont()
        tf.setPixelSize(10)
        tf.setBold(True)
        self._title_lbl.setFont(tf)
        tb_layout.addWidget(self._title_lbl)
        tb_layout.addStretch()

        self._top_bar = top_bar
        root.addWidget(top_bar)

        div = QWidget()
        div.setFixedHeight(1)
        self._top_div = div
        root.addWidget(div)

        # Body
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(14, 18, 14, 16)
        body_layout.setSpacing(18)

        self._photo_row = PathRow("Photos", "📷")
        self._photo_row.changed.connect(self._emit_config)
        body_layout.addWidget(self._photo_row)

        self._video_row = PathRow("Videos", "🎬")
        self._video_row.changed.connect(self._emit_config)
        body_layout.addWidget(self._video_row)

        # Folder structure preview
        self._preview_box = QFrame()
        self._preview_box.setObjectName("previewBox")
        self._preview_box.setFrameShape(QFrame.NoFrame)
        pb_inner = QVBoxLayout(self._preview_box)
        pb_inner.setContentsMargins(14, 12, 14, 12)
        pb_inner.setSpacing(6)

        self._preview_title = QLabel("WHERE FILES WILL GO")
        ptf = QFont()
        ptf.setPixelSize(10)
        ptf.setBold(True)
        self._preview_title.setFont(ptf)
        pb_inner.addWidget(self._preview_title)

        self._preview = QLabel(self._structure_text())
        self._preview.setFont(QFont("Menlo, Courier New, monospace", 11))
        self._preview.setWordWrap(True)
        self._preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pb_inner.addWidget(self._preview)

        body_layout.addWidget(self._preview_box)
        body_layout.addStretch()
        root.addWidget(self._body, stretch=1)

        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(f"DestPanel {{ background: {T.BG_SIDEBAR}; }}")
        self._top_bar.setStyleSheet(
            f"QWidget {{ background: {T.BG_SIDEBAR}; }}"
            f" QLabel {{ color: {T.TEXT_MUTED}; letter-spacing: 1.5px; background: transparent; }}"
        )
        self._top_div.setStyleSheet(f"background: {T.DIVIDER};")
        self._body.setStyleSheet(
            f"background: {T.BG_SIDEBAR};"
            f" QLabel {{ background: transparent; border: none; }}"
        )
        self._preview_box.setStyleSheet(
            f"QFrame#previewBox {{ background: {T.BG_BASE}; border: 1px solid {T.BORDER}; border-radius: 10px; }}"
        )
        self._preview_title.setStyleSheet(
            f"color: {T.TEXT_MUTED}; letter-spacing: 1.5px; background: transparent;"
        )
        self._preview.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; line-height: 1.7; background: transparent;"
        )
        self._photo_row.apply_theme()
        self._video_row.apply_theme()

    def set_templates(self, templates: dict):
        """Folder rules changed — refresh the preview."""
        self._templates = {**DEFAULT_TEMPLATES, **templates}
        self._preview.setText(self._structure_text())

    def set_samples(self, files: list[MediaFile]):
        """Use the first scanned file of each kind as the preview example."""
        self._samples = {}
        for f in files:
            key = _template_key(f.media_type)
            self._samples.setdefault(key, f)
        self._preview.setText(self._structure_text())

    def _structure_text(self) -> str:
        """
        Example destination for each kind of file, resolved from the actual
        folder rules — and from real scanned files when we have them.
        """
        photo_root = self._photo_row.path().name or "Photos"
        video_root = self._video_row.path().name or "Videos"

        groups: dict[str, list[str]] = {}
        for key in ("raw", "photo", "video"):
            template = self._templates.get(key, DEFAULT_TEMPLATES[key])
            sample = self._samples.get(key)
            rel = resolve_template(template, sample) if sample else preview_template(template, key)
            root = video_root if key == "video" else photo_root
            groups.setdefault(root, []).append(rel)

        lines = []
        for root, rels in groups.items():
            if lines:
                lines.append("")
            lines.append(f"{root}/")
            for rel in rels:
                folder, _, name = rel.rpartition("/")
                if folder:
                    lines.append(f"  {folder}/")
                    lines.append(f"    {name}")
                else:
                    lines.append(f"  {name}")
        return "\n".join(lines)

    def set_paths(self, photo: str, video: str):
        self._photo_row.set_path(photo)
        self._video_row.set_path(video)
        self._emit_config()

    def set_drive_root(self, root: Path):
        logger.info("Destination auto-filled: %s", root)
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


def _template_key(media_type: MediaType) -> str:
    if media_type == MediaType.VIDEO:
        return "video"
    if media_type == MediaType.RAW:
        return "raw"
    return "photo"
