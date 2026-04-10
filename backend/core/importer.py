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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .dedup import DedupChecker
from .models import MediaFile
from .rules import destination, DestinationConfig
from .safety import safe_copy, verify_copy, cleanup_temp_files, SafetyError

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    copied:         list[tuple[MediaFile, Path]] = field(default_factory=list)
    skipped:        list[MediaFile]              = field(default_factory=list)  # already exists (dedup)
    conflicts:      list[MediaFile]              = field(default_factory=list)  # dest path exists
    failed:         list[tuple[MediaFile, str]]  = field(default_factory=list)  # copy error
    verified:       list[MediaFile]              = field(default_factory=list)  # passed SHA256 check
    verify_failed:  list[MediaFile]              = field(default_factory=list)  # failed SHA256 check

    @property
    def total_copied(self) -> int:
        return len(self.copied)

    @property
    def total_skipped(self) -> int:
        return len(self.skipped)

    @property
    def total_failed(self) -> int:
        return len(self.failed)

    @property
    def total_conflicts(self) -> int:
        return len(self.conflicts)

    @property
    def total_verified(self) -> int:
        return len(self.verified)

    @property
    def total_verify_failed(self) -> int:
        return len(self.verify_failed)

    def summary(self) -> str:
        mb = sum(f.size_mb for f, _ in self.copied)
        parts = [f"Copied {self.total_copied} files ({mb:.1f} MB)",
                 f"Verified {self.total_verified}",
                 f"Skipped {self.total_skipped}"]
        if self.total_conflicts:
            parts.append(f"Conflicts {self.total_conflicts}")
        if self.total_failed:
            parts.append(f"Failed {self.total_failed}")
        if self.total_verify_failed:
            parts.append(f"Verify failed {self.total_verify_failed}")
        return "  |  ".join(parts)


_WORKERS = 4  # concurrent file copies


def run_import(
    files: list[MediaFile],
    config: DestinationConfig,
    progress_cb: Callable[[int, int, str, int, int, int, int], None] | None = None,
    verify_cb: Callable[[str, bool], None] | None = None,
    cancel_event: threading.Event | None = None,
    session_name: str = "",
) -> ImportResult:
    """
    Import new files from `files` using `config` for destination paths.

    Args:
        files:         Scanned + metadata-enriched MediaFile list from SD card.
        config:        DestinationConfig with photo_base and video_base paths.
        progress_cb:   Optional callback(done, total, filename, bytes_done, bytes_total,
                       file_bytes_done, file_bytes_total).
                       bytes_done/bytes_total reflect aggregate bytes across all files.
                       file_bytes_done/file_bytes_total reflect progress of the current file.
        cancel_event:  Optional threading.Event — set it to stop import between files.

    Returns:
        ImportResult with copied / skipped / failed lists.
    """
    from .models import MediaType
    from backend.db.repository import record_import, record_session, get_imported_source_paths

    result = ImportResult()
    started_at = datetime.utcnow()

    # Clean up any temp files left over from a previous crashed import
    cleaned = cleanup_temp_files(config.photo_base, config.video_base)
    if cleaned:
        logger.info("Resume: removed %d stale temp file(s) from previous crashed import", cleaned)

    # Build dedup index across both destination roots (filesystem check)
    checker_photos = DedupChecker(config.photo_base)
    checker_videos = DedupChecker(config.video_base)
    photo_count = checker_photos.build_index()
    video_count = checker_videos.build_index()
    logger.info("Destination: %d photos, %d videos already on disk", photo_count, video_count)

    # Split new vs already imported (filesystem dedup)
    videos = [f for f in files if f.media_type == MediaType.VIDEO]
    others = [f for f in files if f.media_type != MediaType.VIDEO]

    new_others, skip_others = checker_photos.filter_new(others)
    new_videos, skip_videos = checker_videos.filter_new(videos)

    # Secondary DB-path dedup: catch files that were imported but moved/renamed on dest
    # (filesystem dedup would miss these; DB source_path records are authoritative)
    candidates = new_others + new_videos
    if candidates:
        source_paths = [str(f.path) for f in candidates]
        already_in_db = get_imported_source_paths(source_paths)
        if already_in_db:
            db_skipped = [f for f in candidates if str(f.path) in already_in_db]
            candidates  = [f for f in candidates if str(f.path) not in already_in_db]
            logger.info(
                "Resume: %d file(s) skipped via DB history (previously imported, dest may have moved)",
                len(db_skipped),
            )
            skip_others = skip_others + [f for f in db_skipped if f.media_type != MediaType.VIDEO]
            skip_videos = skip_videos + [f for f in db_skipped if f.media_type == MediaType.VIDEO]

    result.skipped = skip_others + skip_videos
    new_files = candidates

    if not new_files:
        logger.info("Nothing to import — all files already on destination.")
        return result

    total = len(new_files)
    total_bytes = sum(f.size_bytes for f in new_files)
    logger.info("Importing %d new files (%.1f MB)", total, total_bytes / 1_048_576)

    # Derive source root for session recording
    source_root = new_files[0].path.parent if new_files else Path(".")

    # Shared counters — protected by lock
    lock = threading.Lock()
    files_done = 0
    bytes_done_total = 0
    # Track per-file bytes contributed so far (for aggregate progress), keyed by full path
    file_bytes: dict[Path, int] = {}

    def _copy_one(file: MediaFile) -> tuple[MediaFile, Path | None, str | None, bool, str | None]:
        """Copy and verify a single file. Returns (file, dest_path, hash, verify_ok, error_str)."""
        nonlocal files_done, bytes_done_total

        if cancel_event and cancel_event.is_set():
            return file, None, None, False, "cancelled"

        dest_path = destination(file, config)

        def _bytes_cb(chunk_done: int, file_total: int) -> None:
            nonlocal bytes_done_total
            if not progress_cb:
                return
            with lock:
                prev = file_bytes.get(file.path, 0)
                delta = chunk_done - prev
                file_bytes[file.path] = chunk_done
                bytes_done_total += delta
                _done = files_done
                _bd = bytes_done_total
            progress_cb(_done, total, file.name, _bd, total_bytes, chunk_done, file_total)

        try:
            copied_to, file_hash = safe_copy(file.path, dest_path, bytes_cb=_bytes_cb)
            verify_ok = verify_copy(copied_to, file_hash)
            return file, copied_to, file_hash, verify_ok, None
        except SafetyError as e:
            return file, None, None, False, str(e)
        except Exception as e:
            return file, None, None, False, str(e)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_copy_one, f): f for f in new_files}
        for future in as_completed(futures):
            file, copied_to, file_hash, verify_ok, err = future.result()

            if err == "cancelled":
                logger.info("Import cancelled — skipping %s", file.name)
                continue

            with lock:
                files_done += 1
                _done = files_done

            if err is None:
                file.file_hash = file_hash
                with lock:
                    result.copied.append((file, copied_to))
                    if verify_ok:
                        result.verified.append(file)
                    else:
                        result.verify_failed.append(file)
                record_import(file, copied_to)
                logger.debug("Copied [%d/%d] %s → %s", _done, total, file.name, copied_to)
                # Emit a final 100% progress event for this file
                if progress_cb:
                    with lock:
                        _bd = bytes_done_total
                    progress_cb(_done, total, file.name, _bd, total_bytes, file.size_bytes, file.size_bytes)
                if verify_cb:
                    verify_cb(file.name, verify_ok)
            elif "DESTINATION EXISTS" in err:
                logger.warning("Conflict [%d/%d] %s — dest already exists", _done, total, file.name)
                with lock:
                    result.conflicts.append(file)
            else:
                logger.error("Failed [%d/%d] %s — %s", _done, total, file.name, err)
                with lock:
                    result.failed.append((file, err))

    finished_at = datetime.utcnow()
    record_session(
        source_root = source_root,
        dest_root   = config.photo_base.parent,
        total       = total,
        imported    = result.total_copied,
        skipped     = result.total_skipped,
        errors      = result.total_failed,
        verified    = result.total_verified,
        started_at  = started_at,
        finished_at = finished_at,
        name        = session_name,
    )

    logger.info(
        "Import complete: %d copied, %d skipped, %d failed",
        result.total_copied, result.total_skipped, result.total_failed,
    )
    return result
