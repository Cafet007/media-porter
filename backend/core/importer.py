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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import MediaFile, MediaType
from .rules import DEFAULT_TEMPLATES, destination, DestinationConfig
from .safety import safe_copy, verify_copy, cleanup_temp_files, hash_file

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


@dataclass
class PlannedCopy:
    file: MediaFile
    dest_path: Path


@dataclass
class ImportPlan:
    to_copy: list[PlannedCopy] = field(default_factory=list)
    skipped: list[MediaFile] = field(default_factory=list)
    conflicts: list[MediaFile] = field(default_factory=list)

    @property
    def new_files(self) -> list[MediaFile]:
        return [item.file for item in self.to_copy]


_WORKERS = 2  # small concurrency improves speed without swamping external drives
_PROGRESS_INTERVAL_SEC = 0.25


def plan_import(
    files: list[MediaFile],
    config: DestinationConfig,
    *,
    verify_existing: bool = True,
) -> ImportPlan:
    """
    Decide which files should copy, skip, or conflict before workers start.

    The plan is intentionally conservative: filesystem dedup only skips exact
    destination matches, and DB source-path dedup only skips when size and
    capture date match. Weak basename+size matches are not enough to skip a
    file because cameras can roll filenames over.
    """
    from backend.db.repository import get_imported_source_records

    plan = ImportPlan()
    reserved: set[Path] = set()

    source_records = get_imported_source_records([str(f.path) for f in files])

    for file in files:
        if _matches_source_record(file, source_records.get(str(file.path), [])):
            plan.skipped.append(file)
            continue

        dest_path = _planned_destination(file, config, reserved, plan, verify_existing)
        if dest_path is None:
            continue

        reserved.add(dest_path.resolve())
        plan.to_copy.append(PlannedCopy(file=file, dest_path=dest_path))

    return plan


def run_import(
    files: list[MediaFile],
    config: DestinationConfig,
    progress_cb: Callable[[int, int, str, int, int, int, int], None] | None = None,
    verify_cb: Callable[[str, bool], None] | None = None,
    verify_progress_cb: Callable[[str, int, int], None] | None = None,
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
    from backend.db.repository import record_import, record_session

    result = ImportResult()
    started_at = datetime.utcnow()

    plan = plan_import(files, config)
    result.skipped = list(plan.skipped)
    result.conflicts = list(plan.conflicts)
    new_files = plan.to_copy

    if not new_files:
        logger.info("Nothing to import — all files already on destination.")
        return result

    # Clean up temp files left over from a previous crashed import — only in
    # the folders this run writes to, so we never walk the whole archive.
    cleaned = cleanup_temp_files(
        *{item.dest_path.parent for item in new_files}, recursive=False,
    )
    if cleaned:
        logger.info("Resume: removed %d stale temp file(s) from previous crashed import", cleaned)

    total = len(new_files)
    total_bytes = sum(item.file.size_bytes for item in new_files)
    logger.info("Importing %d new files (%.1f MB)", total, total_bytes / 1_048_576)

    # Derive source root for session recording
    source_root = new_files[0].file.path.parent if new_files else Path(".")

    # Shared counters — protected by lock
    lock = threading.Lock()
    files_done = 0
    bytes_done_total = 0
    # Track per-file bytes contributed so far (for aggregate progress), keyed by full path
    file_bytes: dict[Path, int] = {}
    copy_progress_last_emit: dict[Path, float] = {}
    verify_progress_last_emit: dict[Path, float] = {}

    def _copy_one(item: PlannedCopy) -> tuple[MediaFile, Path | None, str | None, bool, str | None]:
        """Copy and verify a single file. Returns (file, dest_path, hash, verify_ok, error_str)."""
        nonlocal files_done, bytes_done_total
        file = item.file

        if cancel_event and cancel_event.is_set():
            return file, None, None, False, "cancelled"

        dest_path = item.dest_path

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
                now = time.monotonic()
                last_emit = copy_progress_last_emit.get(file.path, 0)
                should_emit = (
                    chunk_done >= file_total
                    or now - last_emit >= _PROGRESS_INTERVAL_SEC
                )
                if should_emit:
                    copy_progress_last_emit[file.path] = now
            if not should_emit:
                return
            progress_cb(_done, total, file.name, _bd, total_bytes, chunk_done, file_total)

        def _verify_bytes_cb(chunk_done: int, file_total: int) -> None:
            if not verify_progress_cb:
                return
            with lock:
                now = time.monotonic()
                last_emit = verify_progress_last_emit.get(file.path, 0)
                should_emit = (
                    chunk_done >= file_total
                    or now - last_emit >= _PROGRESS_INTERVAL_SEC
                )
                if should_emit:
                    verify_progress_last_emit[file.path] = now
            if should_emit:
                verify_progress_cb(file.name, chunk_done, file_total)

        try:
            copied_to, file_hash = safe_copy(file.path, dest_path, bytes_cb=_bytes_cb)
            verify_ok = verify_copy(copied_to, file_hash, bytes_cb=_verify_bytes_cb)
            return file, copied_to, file_hash, verify_ok, None
        except Exception as e:
            return file, None, None, False, str(e)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_copy_one, item): item.file for item in new_files}
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
                if verify_ok:
                    record_import(file, copied_to)
                    logger.debug("Copied [%d/%d] %s → %s", _done, total, file.name, copied_to)
                else:
                    # Not recorded in history, so the next run re-checks this
                    # file (it will show as a conflict against the bad copy).
                    logger.error("Verify failed [%d/%d] %s → %s", _done, total, file.name, copied_to)
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
        total       = len(files),
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


# ---------------------------------------------------------------------------
# Planning helpers
# ---------------------------------------------------------------------------

def _planned_destination(
    file: MediaFile,
    config: DestinationConfig,
    reserved: set[Path],
    plan: ImportPlan,
    verify_existing: bool,
) -> Path | None:
    uses_counter = "{counter}" in _template_for(file, config)
    counters = range(1, 1_000_000) if uses_counter else range(1, 2)

    for counter in counters:
        dest_path = destination(file, config, counter=counter)
        dest_key = dest_path.resolve()

        if dest_key in reserved:
            if uses_counter:
                continue
            logger.warning("Batch conflict: multiple files resolve to %s", dest_path)
            plan.conflicts.append(file)
            return None

        if dest_path.exists():
            if _same_existing_file(file, dest_path, verify_existing):
                plan.skipped.append(file)
                return None
            if uses_counter:
                continue
            logger.warning("Conflict: %s exists but does not match %s", dest_path, file.path)
            plan.conflicts.append(file)
            return None

        return dest_path

    logger.warning("Conflict: no available counter destination for %s", file.path)
    plan.conflicts.append(file)
    return None


def _template_for(file: MediaFile, config: DestinationConfig) -> str:
    if file.media_type == MediaType.VIDEO:
        key = "video"
    elif file.media_type == MediaType.RAW:
        key = "raw"
    else:
        key = "photo"
    return config.templates.get(key, DEFAULT_TEMPLATES.get(key, "{date}/{original_name}.{ext}"))


def _same_existing_file(file: MediaFile, dest_path: Path, verify_existing: bool) -> bool:
    try:
        if dest_path.stat().st_size != file.size_bytes:
            return False
        if not verify_existing:
            return True
        return hash_file(file.path) == hash_file(dest_path)
    except OSError:
        return False


def _matches_source_record(
    file: MediaFile,
    records: list[tuple[int | None, datetime | None, str | None]],
) -> bool:
    if not file.captured_at:
        return False

    for file_size, captured_at, dest_path in records:
        if file_size != file.size_bytes or captured_at is None:
            continue
        if _same_capture_time(file.captured_at, captured_at):
            return _recorded_destination_exists(dest_path, file_size)
    return False


def _same_capture_time(a: datetime, b: datetime) -> bool:
    a = a.replace(tzinfo=None)
    b = b.replace(tzinfo=None)
    return abs((a - b).total_seconds()) < 1


def _recorded_destination_exists(dest_path: str | None, expected_size: int | None) -> bool:
    if not dest_path:
        return False
    try:
        path = Path(dest_path)
        return path.is_file() and (expected_size is None or path.stat().st_size == expected_size)
    except OSError:
        return False
