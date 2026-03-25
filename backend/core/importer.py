"""
Importer — copies new files from SD card to external drive.

Flow:
  1. Scan SD card
  2. Extract metadata (date + kind)
  3. Dedup check — skip files already on external drive
  4. Resolve destination path via rules engine
  5. Safe copy (atomic, never deletes, never overwrites)
  6. Report results
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .dedup import DedupChecker
from .models import MediaFile
from .rules import destination, DestinationConfig
from .safety import safe_copy, SafetyError

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    copied:   list[tuple[MediaFile, Path]] = field(default_factory=list)
    skipped:  list[MediaFile]              = field(default_factory=list)  # already exists
    failed:   list[tuple[MediaFile, str]]  = field(default_factory=list)  # error message

    @property
    def total_copied(self) -> int:
        return len(self.copied)

    @property
    def total_skipped(self) -> int:
        return len(self.skipped)

    @property
    def total_failed(self) -> int:
        return len(self.failed)

    def summary(self) -> str:
        mb = sum(f.size_mb for f, _ in self.copied)
        return (
            f"Copied {self.total_copied} files ({mb:.1f} MB)  |  "
            f"Skipped {self.total_skipped} (already imported)  |  "
            f"Failed {self.total_failed}"
        )


def run_import(
    files: list[MediaFile],
    config: DestinationConfig,
    progress_cb: Callable[[int, int, str, int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> ImportResult:
    """
    Import new files from `files` using `config` for destination paths.

    Args:
        files:         Scanned + metadata-enriched MediaFile list from SD card.
        config:        DestinationConfig with photo_base and video_base paths.
        progress_cb:   Optional callback(done, total, filename, bytes_done, bytes_total).
        cancel_event:  Optional threading.Event — set it to stop import between files.

    Returns:
        ImportResult with copied / skipped / failed lists.
    """
    from .models import MediaType
    from backend.db.repository import record_import, record_session

    result = ImportResult()
    started_at = datetime.utcnow()

    # Build dedup index across both destination roots
    checker_photos = DedupChecker(config.photo_base)
    checker_videos = DedupChecker(config.video_base)
    photo_count = checker_photos.build_index()
    video_count = checker_videos.build_index()
    logger.info("Destination: %d photos, %d videos already imported", photo_count, video_count)

    # Split new vs already imported
    videos = [f for f in files if f.media_type == MediaType.VIDEO]
    others = [f for f in files if f.media_type != MediaType.VIDEO]

    new_others, skip_others = checker_photos.filter_new(others)
    new_videos, skip_videos = checker_videos.filter_new(videos)

    result.skipped = skip_others + skip_videos
    new_files = new_others + new_videos

    if not new_files:
        logger.info("Nothing to import — all files already on destination.")
        return result

    total = len(new_files)
    logger.info("Importing %d new files", total)

    # Derive source root for session recording
    source_root = new_files[0].path.parent if new_files else Path(".")

    for i, file in enumerate(new_files, 1):
        if cancel_event and cancel_event.is_set():
            logger.info("Import cancelled by user at file %d/%d", i, total)
            break

        dest_path = destination(file, config)

        def _bytes_cb(done: int, total_bytes: int, _i=i, _name=file.name) -> None:
            if progress_cb:
                progress_cb(_i, total, _name, done, total_bytes)

        try:
            copied_to, file_hash = safe_copy(file.path, dest_path, bytes_cb=_bytes_cb)
            file.file_hash = file_hash
            result.copied.append((file, copied_to))
            record_import(file, copied_to)
            logger.debug("Copied [%d/%d] %s → %s", i, total, file.name, copied_to)
        except SafetyError as e:
            logger.error("Safety blocked [%d/%d] %s — %s", i, total, file.name, e)
            result.failed.append((file, str(e)))
        except Exception as e:
            logger.error("Copy failed [%d/%d] %s — %s", i, total, file.name, e)
            result.failed.append((file, str(e)))

    finished_at = datetime.utcnow()
    record_session(
        source_root = source_root,
        dest_root   = config.photo_base.parent,
        total       = total,
        imported    = result.total_copied,
        skipped     = result.total_skipped,
        errors      = result.total_failed,
        started_at  = started_at,
        finished_at = finished_at,
    )

    logger.info(
        "Import complete: %d copied, %d skipped, %d failed",
        result.total_copied, result.total_skipped, result.total_failed,
    )
    return result
