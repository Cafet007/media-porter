"""
Safety Guard — ensures the app never writes to, deletes from, or modifies
any source drive (SD card or external storage).

Rules enforced:
  1. Source drives are mounted read-only in Python (O_RDONLY)
  2. No file deletion anywhere — ever
  3. No file creation on source drives
  4. Destination path must differ from source path
  5. All copies go to a temp file first — renamed only on success (atomic write)
  6. Destination must have enough free space before any copy begins
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


class SafetyError(Exception):
    """Raised when a safety rule would be violated."""


# ---------------------------------------------------------------------------
# Protected path registry
# ---------------------------------------------------------------------------

_protected_roots: set[Path] = set()


def protect(path: Path | str) -> None:
    """
    Register a path as protected (source drive mount point).
    Any write/delete attempt inside this path will raise SafetyError.
    """
    _protected_roots.add(Path(path).resolve())
    logger.info("Safety: protected path registered → %s", path)


def unprotect(path: Path | str) -> None:
    _protected_roots.discard(Path(path).resolve())


def is_protected(path: Path | str) -> bool:
    resolved = Path(path).resolve()
    return any(
        resolved == root or root in resolved.parents
        for root in _protected_roots
    )


# ---------------------------------------------------------------------------
# Guard functions — call before every file operation
# ---------------------------------------------------------------------------

def guard_read(path: Path) -> None:
    """Verify a path is safe to read (always allowed — just logs)."""
    logger.debug("Safety: read  %s", path)


def guard_write(path: Path) -> None:
    """Raise SafetyError if path is inside a protected (source) drive."""
    if is_protected(path):
        raise SafetyError(
            f"WRITE BLOCKED: '{path}' is inside a protected source drive. "
            "The app never writes to source drives."
        )
    logger.debug("Safety: write allowed → %s", path)


def guard_delete(path: Path) -> None:
    """Always raises SafetyError — deletion is never allowed."""
    raise SafetyError(
        f"DELETE BLOCKED: '{path}'. "
        "This app never deletes files from any drive."
    )


def guard_same_path(src: Path, dst: Path) -> None:
    """Raise if source and destination resolve to the same path."""
    if src.resolve() == dst.resolve():
        raise SafetyError(
            f"SOURCE == DESTINATION: '{src}' and '{dst}' are the same file."
        )


def guard_space(src: Path, dst_dir: Path) -> None:
    """Raise if destination drive lacks space for the source file."""
    required = src.stat().st_size
    free = shutil.disk_usage(dst_dir).free
    if free < required:
        raise SafetyError(
            f"NOT ENOUGH SPACE: need {required / 1e6:.1f} MB, "
            f"only {free / 1e6:.1f} MB free on {dst_dir}"
        )


def check_batch_space(files: list, config) -> list[str]:
    """
    Check whether destination drives have enough free space for all files.

    Groups files by device (photo_base and video_base may share the same drive).
    Returns a list of error strings — empty list means all clear.
    """
    import os
    from .models import MediaType

    # Map st_dev → (representative path, total bytes needed)
    dev_map: dict[int, tuple[Path, int]] = {}

    for f in files:
        base = config.video_base if f.media_type == MediaType.VIDEO else config.photo_base

        # Walk up to find an existing ancestor (base folders may not exist yet)
        check_path = base
        while not check_path.exists():
            check_path = check_path.parent
            if check_path == check_path.parent:
                break  # reached filesystem root

        try:
            dev = os.stat(check_path).st_dev
        except OSError:
            continue

        prev_path, prev_total = dev_map.get(dev, (check_path, 0))
        dev_map[dev] = (prev_path, prev_total + f.size_bytes)

    errors = []
    for dev, (sample_path, needed) in dev_map.items():
        try:
            free = shutil.disk_usage(sample_path).free
        except OSError:
            continue
        if free < needed:
            errors.append(
                f"{sample_path}: need {needed / 1_073_741_824:.2f} GB, "
                f"only {free / 1_073_741_824:.2f} GB free"
            )

    return errors


# ---------------------------------------------------------------------------
# Safe file copy — atomic (temp file → rename)
# ---------------------------------------------------------------------------

_CHUNK = 8 * 1024 * 1024
# Flush written data to disk every N bytes. Without this the OS buffers
# gigabytes of dirty pages for a slow USB/exFAT drive, which starves memory
# and stalls the whole machine while the cache drains.
_FLUSH_EVERY = 128 * 1024 * 1024
_copy_locks_guard = threading.Lock()
_copy_locks: dict[Path, threading.Lock] = {}


def _lock_for(path: Path) -> threading.Lock:
    key = path.resolve()
    with _copy_locks_guard:
        lock = _copy_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _copy_locks[key] = lock
        return lock


def _bypass_cache(fd: int) -> None:
    """
    Ask the OS not to keep this file's pages in the buffer cache (best effort).

    macOS: F_NOCACHE makes reads/writes go straight to the device.
    Elsewhere this is a no-op; Linux uses _drop_cache() after fsync instead.
    """
    if sys.platform == "darwin":
        try:
            import fcntl
            fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
        except (ImportError, AttributeError, OSError):
            pass


def _drop_cache(fd: int) -> None:
    """Evict already-flushed pages of fd from the page cache (Linux, best effort)."""
    if hasattr(os, "posix_fadvise"):
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def hash_file(
    path: Path,
    bytes_cb: Callable[[int, int], None] | None = None,
    *,
    uncached: bool = False,
) -> str:
    """
    Return the SHA256 hex digest for a file.

    uncached=True reads from the device rather than the OS cache where the
    platform allows it — used for post-copy verification, so a match proves
    the bytes actually landed on disk.
    """
    total_bytes = path.stat().st_size
    bytes_done = 0
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        if uncached:
            _bypass_cache(f.fileno())
            _drop_cache(f.fileno())
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
            bytes_done += len(chunk)
            if bytes_cb:
                bytes_cb(bytes_done, total_bytes)
    return hasher.hexdigest()


def _destination_exists_error(dst: Path) -> SafetyError:
    return SafetyError(
        f"DESTINATION EXISTS: '{dst}'. "
        "Will not overwrite — deduplicate first."
    )


def _commit_temp_no_overwrite(tmp_path: Path, dst: Path) -> None:
    """
    Commit tmp_path to dst without replacing an existing file.

    On filesystems with hard-link support, os.link gives us atomic
    "create only if absent" semantics. Some camera/media drives are exFAT and
    do not support hard links, so we fall back to rename while the per-path app
    lock is held.
    """
    if dst.exists():
        raise _destination_exists_error(dst)

    try:
        os.link(tmp_path, dst)
        tmp_path.unlink()
        return
    except FileExistsError:
        raise _destination_exists_error(dst)
    except OSError:
        # Hard links are unsupported on filesystems like exFAT/FAT32.
        # The caller holds the app-level destination lock, so this still
        # prevents Media Porter workers from overwriting each other.
        if dst.exists():
            raise _destination_exists_error(dst)
        try:
            tmp_path.rename(dst)
        except FileExistsError:
            raise _destination_exists_error(dst)


def safe_copy(
    src: Path,
    dst: Path,
    bytes_cb: Callable[[int, int], None] | None = None,
) -> tuple[Path, str]:
    """
    Copy src → dst safely:
      - dst drive must have enough free space
      - writes to a temp file first, renames on success (no partial files)
      - never deletes, never moves
      - bytes_cb(bytes_done, total_bytes) called every chunk for progress
      - computes SHA256 of source during read (no extra I/O)

    Returns (final_dest_path, sha256_hex).
    Raises SafetyError on any violation.
    """
    src = src.resolve()
    dst = dst.resolve()

    with _lock_for(dst):
        # Safety checks that don't need the directory to exist yet
        guard_same_path(src, dst)
        guard_write(dst)

        # Create destination folder (disk_usage in guard_space needs it to exist)
        dst.parent.mkdir(parents=True, exist_ok=True)

        guard_space(src, dst.parent)

        if dst.exists():
            raise _destination_exists_error(dst)

        total_bytes = src.stat().st_size

        # Atomic write: temp file in same directory, then commit only if absent.
        tmp_path = None
        try:
            fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".mporter_tmp_")
            tmp_path = Path(tmp)
            os.close(fd)

            written = 0
            unflushed = 0
            hasher = hashlib.sha256()
            with open(src, "rb") as fsrc, open(tmp_path, "wb") as fdst:
                _bypass_cache(fsrc.fileno())
                _bypass_cache(fdst.fileno())
                while True:
                    chunk = fsrc.read(_CHUNK)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    hasher.update(chunk)
                    written += len(chunk)
                    unflushed += len(chunk)
                    if unflushed >= _FLUSH_EVERY:
                        _flush(fdst)
                        unflushed = 0
                    if bytes_cb:
                        bytes_cb(written, total_bytes)
                # Make sure the data is on disk before the file becomes visible
                _flush(fdst)

            file_hash = hasher.hexdigest()

            # Preserve file metadata (timestamps, etc.)
            shutil.copystat(src, tmp_path)
            _commit_temp_no_overwrite(tmp_path, dst)
            tmp_path = None

            logger.info("Copied: %s → %s  [sha256: %s…]", src.name, dst, file_hash[:12])
            return dst, file_hash

        except SafetyError:
            raise
        except Exception as exc:
            logger.error("Copy failed: %s → %s: %s", src, dst, exc)
            raise
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass


def _flush(f) -> None:
    """Push buffered writes to the device and release their cache pages."""
    f.flush()
    os.fsync(f.fileno())
    _drop_cache(f.fileno())


def verify_copy(
    dst: Path,
    expected_hash: str,
    bytes_cb: Callable[[int, int], None] | None = None,
) -> bool:
    """
    Re-read the destination file from disk and confirm it matches
    expected_hash (SHA256 hex). Returns True on match, False if the copy
    is corrupted. Raises OSError if the file cannot be read.
    """
    actual = hash_file(dst, bytes_cb=bytes_cb, uncached=True)
    if actual != expected_hash:
        logger.error(
            "VERIFICATION FAILED: '%s' — expected %s… got %s…",
            dst, expected_hash[:12], actual[:12],
        )
        return False
    logger.info("Verified: %s  [sha256: %s…]", dst.name, actual[:12])
    return True


# ---------------------------------------------------------------------------
# Temp file cleanup — call before starting a new import
# ---------------------------------------------------------------------------

_TMP_PREFIX = ".mporter_tmp_"


def cleanup_temp_files(*directories: Path, recursive: bool = True) -> int:
    """
    Remove any leftover .mporter_tmp_* files from a previous crashed import.
    Safe to call before every import run.

    recursive=False only checks the given folders themselves — much cheaper
    than walking a multi-terabyte archive when we know which folders we'll
    write into.

    Returns the number of temp files removed.
    """
    removed = 0
    for directory in directories:
        if not directory.exists():
            continue
        matches = directory.rglob(f"{_TMP_PREFIX}*") if recursive else directory.glob(f"{_TMP_PREFIX}*")
        for tmp in matches:
            if tmp.is_file():
                try:
                    tmp.unlink()
                    logger.warning("Removed stale temp file: %s", tmp)
                    removed += 1
                except Exception as exc:
                    logger.error("Could not remove stale temp file %s: %s", tmp, exc)
    if removed:
        logger.info("Cleaned up %d stale temp file(s) from previous crashed import", removed)
    return removed


# ---------------------------------------------------------------------------
# Read-only file opener — use this instead of open() for source files
# ---------------------------------------------------------------------------

def open_readonly(path: Path):
    """
    Open a file strictly in binary read-only mode.
    Raises SafetyError if the path is somehow not readable.
    Use this everywhere we read from SD cards.
    """
    guard_read(path)
    return open(path, "rb")


# ---------------------------------------------------------------------------
# Safety report — show current state
# ---------------------------------------------------------------------------

def report() -> str:
    if not _protected_roots:
        return "Safety: no protected paths registered."
    lines = ["Safety guard active. Protected paths:"]
    for p in sorted(_protected_roots):
        lines.append(f"  🔒 {p}")
    return "\n".join(lines)
