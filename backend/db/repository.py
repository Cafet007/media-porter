"""
Repository — CRUD for import history (imports + sessions tables).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.models import MediaFile
from .models import ImportRecord, ImportSession, get_engine

logger = logging.getLogger(__name__)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

def record_import(file: MediaFile, dest_path: Path) -> bool:
    """
    Record a successfully imported file.
    Returns True if recorded, False if the hash already exists (duplicate).
    """
    if not file.file_hash:
        logger.warning("record_import: no hash on %s — skipping", file.name)
        return False

    try:
        with Session(_get_engine()) as session:
            if session.query(ImportRecord).filter_by(file_hash=file.file_hash).count():
                return False
            session.add(ImportRecord(
                file_hash    = file.file_hash,
                source_path  = str(file.path),
                dest_path    = str(dest_path),
                file_size    = file.size,
                media_type   = file.media_type.value if file.media_type else None,
                camera_make  = file.camera_make,
                camera_model = file.camera_model,
                captured_at  = file.captured_at,
            ))
            session.commit()
            return True
    except Exception as e:
        logger.error("record_import failed for %s: %s", file.name, e)
        return False


def is_hash_imported(file_hash: str) -> bool:
    """Return True if this SHA256 hash was already imported."""
    try:
        with Session(_get_engine()) as session:
            return session.query(ImportRecord).filter_by(file_hash=file_hash).count() > 0
    except Exception:
        return False


def is_path_imported(source_path: Path | str) -> bool:
    """
    Return True if a file with this exact source path was previously imported.
    Used as a secondary cross-session dedup check during resume/recovery.
    """
    try:
        with Session(_get_engine()) as session:
            return (
                session.query(ImportRecord)
                .filter_by(source_path=str(source_path))
                .count() > 0
            )
    except Exception:
        return False


def get_imported_source_paths(source_paths: list[str]) -> set[str]:
    """
    Given a list of source path strings, return the subset that have been
    previously imported. More efficient than calling is_path_imported() in a loop.
    """
    if not source_paths:
        return set()
    try:
        with Session(_get_engine()) as session:
            records = (
                session.query(ImportRecord.source_path)
                .filter(ImportRecord.source_path.in_(source_paths))
                .all()
            )
            return {r.source_path for r in records}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def record_session(
    source_root: Path,
    dest_root: Path,
    total: int,
    imported: int,
    skipped: int,
    errors: int,
    started_at: datetime,
    finished_at: datetime,
    verified: int = 0,
    name: str = "",
) -> None:
    """Record a completed import session."""
    try:
        with Session(_get_engine()) as session:
            session.add(ImportSession(
                name        = name or None,
                source_root = str(source_root),
                dest_root   = str(dest_root),
                total_files = total,
                imported    = imported,
                skipped     = skipped,
                errors      = errors,
                verified    = verified,
                started_at  = started_at,
                finished_at = finished_at,
            ))
            session.commit()
    except Exception as e:
        logger.error("record_session failed: %s", e)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_history(limit: int = 500) -> list[ImportRecord]:
    """Return most recent imports, newest first."""
    try:
        with Session(_get_engine()) as session:
            records = (
                session.query(ImportRecord)
                .order_by(ImportRecord.imported_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return records
    except Exception as e:
        logger.error("get_history failed: %s", e)
        return []


def search_history(
    query: str = "",
    camera: str = "",
    media_type: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 1000,
) -> list[ImportRecord]:
    """
    Search import history with optional filters. All filters are combinable.

    Args:
        query:      Substring match against filename (source_path).
        camera:     Exact match against "make model" string (case-insensitive).
        media_type: One of "photo", "raw", "video" — or empty for all.
        date_from:  Include only records with captured_at >= date_from.
        date_to:    Include only records with captured_at <= date_to.
        limit:      Max records to return.

    Returns list[ImportRecord] ordered by imported_at descending.
    """
    try:
        with Session(_get_engine()) as session:
            q = session.query(ImportRecord)

            if query.strip():
                pattern = f"%{query.strip()}%"
                q = q.filter(ImportRecord.source_path.ilike(pattern))

            if camera.strip():
                # Match against "make model" concatenation
                parts = camera.strip().lower().split()
                for part in parts:
                    q = q.filter(
                        or_(
                            ImportRecord.camera_make.ilike(f"%{part}%"),
                            ImportRecord.camera_model.ilike(f"%{part}%"),
                        )
                    )

            if media_type.strip():
                q = q.filter(ImportRecord.media_type == media_type.strip().lower())

            if date_from is not None:
                q = q.filter(ImportRecord.captured_at >= date_from)

            if date_to is not None:
                q = q.filter(ImportRecord.captured_at <= date_to)

            records = (
                q.order_by(ImportRecord.imported_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return records
    except Exception as e:
        logger.error("search_history failed: %s", e)
        return []


def get_distinct_cameras() -> list[str]:
    """
    Return a sorted list of unique camera strings ("Make Model") from the DB.
    Used to populate the camera filter dropdown in the history panel.
    Returns an empty list if the DB is empty or unavailable.
    """
    try:
        with Session(_get_engine()) as session:
            rows = (
                session.query(
                    ImportRecord.camera_make,
                    ImportRecord.camera_model,
                )
                .distinct()
                .all()
            )
            cameras = set()
            for make, model in rows:
                parts = " ".join(filter(None, [make, model])).strip()
                if parts:
                    cameras.add(parts)
            return sorted(cameras)
    except Exception as e:
        logger.error("get_distinct_cameras failed: %s", e)
        return []


def get_sessions(limit: int = 100) -> list[ImportSession]:
    """Return most recent sessions, newest first."""
    try:
        with Session(_get_engine()) as session:
            records = (
                session.query(ImportSession)
                .order_by(ImportSession.started_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return records
    except Exception as e:
        logger.error("get_sessions failed: %s", e)
        return []
