"""
Database models — SQLAlchemy ORM for import history.

Tables:
  imports  — one row per successfully imported file (keyed by SHA256)
  sessions — one row per import session (scan → import run)
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

_DB_PATH = Path.home() / ".media-mporter" / "history.db"


class Base(DeclarativeBase):
    pass


class ImportRecord(Base):
    __tablename__ = "imports"

    id:           Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_hash:    Mapped[str]             = mapped_column(String, nullable=False, unique=True, index=True)
    source_path:  Mapped[str]             = mapped_column(String, nullable=False)
    dest_path:    Mapped[str]             = mapped_column(String, nullable=False)
    file_size:    Mapped[Optional[int]]      = mapped_column(BigInteger)
    media_type:   Mapped[Optional[str]]      = mapped_column(String)
    camera_make:  Mapped[Optional[str]]      = mapped_column(String)
    camera_model: Mapped[Optional[str]]      = mapped_column(String)
    captured_at:  Mapped[Optional[datetime]] = mapped_column(DateTime)
    imported_at:  Mapped[datetime]        = mapped_column(DateTime, default=datetime.utcnow)


class ImportSession(Base):
    __tablename__ = "sessions"

    id:          Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_root: Mapped[str]             = mapped_column(String, nullable=False)
    dest_root:   Mapped[str]             = mapped_column(String, nullable=False)
    total_files: Mapped[Optional[int]]      = mapped_column(Integer)
    imported:    Mapped[Optional[int]]      = mapped_column(Integer)
    skipped:     Mapped[Optional[int]]      = mapped_column(Integer)
    errors:      Mapped[Optional[int]]      = mapped_column(Integer)
    started_at:  Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


def get_engine():
    """Return (and create if needed) the SQLite engine, creating tables on first run."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{_DB_PATH}", echo=False)
    Base.metadata.create_all(engine)
    return engine
