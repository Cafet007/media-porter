"""
Thumbnail Loader — generates thumbnails on background threads for the views.

Requests come from painting, so they arrive for whatever rows are on screen.
Work is served newest-first (LIFO): after a fast scroll the rows now visible
load before the ones that already scrolled away, and the queue is capped so
stale requests are dropped rather than piling up.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from backend.core.models import MediaType
from backend.core.thumbnails import thumbnail

logger = logging.getLogger(__name__)

_WORKERS = 2          # thumbnails read from the card — keep it gentle
_MAX_QUEUE = 300


class ThumbnailLoader(QObject):
    ready = Signal(str, QImage)            # path, image (null image = no preview)
    _done = Signal(str, QImage, int)       # internal: from worker threads

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: deque[tuple[str, MediaType, int]] = deque()
        self._pending: set[str] = set()
        self._generation = 0
        self._cond = threading.Condition()
        self._done.connect(self._on_done)
        for i in range(_WORKERS):
            threading.Thread(target=self._run, daemon=True, name=f"Thumb{i}").start()

    def request(self, path: Path | str, media_type: MediaType) -> None:
        key = str(path)
        with self._cond:
            if key in self._pending:
                return
            self._pending.add(key)
            self._queue.append((key, media_type, self._generation))
            while len(self._queue) > _MAX_QUEUE:
                old_key, _, _ = self._queue.popleft()
                self._pending.discard(old_key)   # will be re-requested if painted again
            self._cond.notify()

    def reset(self) -> None:
        """Forget queued work — call when the file list is replaced."""
        with self._cond:
            self._generation += 1
            self._queue.clear()
            self._pending.clear()

    # ------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._queue:
                    self._cond.wait()
                key, media_type, generation = self._queue.pop()   # newest first
            data = thumbnail(Path(key), media_type)
            image = QImage()
            if data:
                image.loadFromData(data)
            try:
                self._done.emit(key, image, generation)
            except RuntimeError:
                return   # loader destroyed (app quitting)

    def _on_done(self, key: str, image: QImage, generation: int) -> None:
        with self._cond:
            if generation != self._generation:
                return
            self._pending.discard(key)
        self.ready.emit(key, image)
