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

_DB_PATH = Path.home() / ".media-porter" / "history.db"


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
    name:        Mapped[Optional[str]]      = mapped_column(String)
    source_root: Mapped[str]             = mapped_column(String, nullable=False)
    dest_root:   Mapped[str]             = mapped_column(String, nullable=False)
    total_files: Mapped[Optional[int]]      = mapped_column(Integer)
    imported:    Mapped[Optional[int]]      = mapped_column(Integer)
    skipped:     Mapped[Optional[int]]      = mapped_column(Integer)
    errors:      Mapped[Optional[int]]      = mapped_column(Integer)
    verified:    Mapped[Optional[int]]      = mapped_column(Integer)
    started_at:  Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


def get_engine():
    """Return (and create if needed) the SQLite engine, creating tables on first run."""
    from sqlalchemy import text, inspect as sa_inspect
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{_DB_PATH}", echo=False)
    Base.metadata.create_all(engine)
    # Migrate: add columns that may not exist in older DB files
    _migrate(engine)
    return engine


def _migrate(engine) -> None:
    """Apply additive schema migrations to existing DBs."""
    from sqlalchemy import text, inspect as sa_inspect
    inspector = sa_inspect(engine)
    with engine.connect() as conn:
        if "sessions" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("sessions")}
            # sessions.verified — added in Phase 1
            if "verified" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN verified INTEGER"))
                conn.commit()
            # sessions.name — added in Phase 2
            if "name" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN name TEXT"))
                conn.commit()
