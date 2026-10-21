"""
Icons — small images that Qt stylesheets need as files (check box marks).

Stylesheets can only reference images by path, so we paint them once with
QPainter into ~/.media-porter/ui (1x and @2x for Retina) and hand out the
1x path; Qt picks the @2x file automatically on HiDPI screens.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPolygonF

_DIR = Path.home() / ".media-porter" / "ui"
_SIZE = 16
_VERSION = 1   # bump to regenerate after changing the drawings


def _paint_check(p: QPainter, s: float):
    p.setPen(QPen(QColor("white"), s * 0.14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline(QPolygonF([
        QPointF(s * 0.26, s * 0.52), QPointF(s * 0.43, s * 0.69), QPointF(s * 0.75, s * 0.33),
    ]))


def _paint_dash(p: QPainter, s: float):
    p.setPen(QPen(QColor("white"), s * 0.14, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(s * 0.28, s * 0.5), QPointF(s * 0.72, s * 0.5))


_DRAWINGS = {"check": _paint_check, "dash": _paint_dash}


def icon_path(name: str) -> str:
    """Return a stylesheet-ready path (forward slashes) for a named icon."""
    base = _DIR / f"{name}_v{_VERSION}.png"
    if not base.exists():
        _DIR.mkdir(parents=True, exist_ok=True)
        for scale, path in ((1, base), (2, base.with_name(f"{name}_v{_VERSION}@2x.png"))):
            px = _SIZE * scale
            img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            _DRAWINGS[name](p, px)
            p.end()
            img.save(str(path))
    return base.as_posix()


def indicator_style(selector: str, *, accent: str, border: str, disabled_bg: str, disabled_border: str) -> str:
    """Rounded check boxes that stay visible in both themes."""
    return f"""
        {selector}::indicator {{
            width: 16px; height: 16px; border-radius: 4px;
            border: 1.5px solid {border}; background: transparent;
        }}
        {selector}::indicator:checked {{
            background: {accent}; border-color: {accent}; image: url("{icon_path('check')}");
        }}
        {selector}::indicator:indeterminate {{
            background: {accent}; border-color: {accent}; image: url("{icon_path('dash')}");
        }}
        {selector}::indicator:disabled {{
            background: {disabled_bg}; border-color: {disabled_border}; image: none;
        }}
    """
