"""
Repository — CRUD for import history (imports + sessions tables).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

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
) -> None:
    """Record a completed import session."""
    try:
        with Session(_get_engine()) as session:
            session.add(ImportSession(
                source_root = str(source_root),
                dest_root   = str(dest_root),
                total_files = total,
                imported    = imported,
                skipped     = skipped,
                errors      = errors,
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
