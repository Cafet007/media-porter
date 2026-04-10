"""
Tests for backend/db/repository.py — search_history() and get_distinct_cameras().

Each test uses an isolated in-memory SQLite DB via monkeypatch so it never
touches the real ~/.media-porter/history.db.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import backend.db.models as db_models
import backend.db.repository as db_repo
from backend.db.models import ImportRecord, get_engine
from backend.db.repository import (
    search_history,
    get_distinct_cameras,
    record_import,
)
from backend.core.models import MediaFile, MediaType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own in-memory DB. Never touches the real DB."""
    test_db = tmp_path / "test_history.db"
    monkeypatch.setattr(db_models, "_DB_PATH", test_db)
    db_repo._engine = None  # force re-init
    yield
    db_repo._engine = None  # cleanup


def _make_record(
    src_dir: Path,
    name: str,
    media_type: MediaType = MediaType.PHOTO,
    camera_make: str = "Sony",
    camera_model: str = "ILCE-6300",
    captured_at: datetime | None = None,
) -> MediaFile:
    """Create and record a MediaFile in the test DB. Returns the MediaFile."""
    import hashlib, os
    p = src_dir / name
    p.write_bytes(os.urandom(64))
    f = MediaFile(path=p, media_type=media_type, size=64)
    f.camera_make = camera_make
    f.camera_model = camera_model
    f.captured_at = captured_at or datetime(2026, 4, 1, 10, 0)
    f.file_hash = hashlib.sha256(p.read_bytes()).hexdigest()
    record_import(f, Path(f"/dest/{name}"))
    return f


# ---------------------------------------------------------------------------
# search_history — filename filter
# ---------------------------------------------------------------------------

def test_search_by_filename(tmp_path):
    _make_record(tmp_path, "DSC00001.ARW", MediaType.RAW)
    _make_record(tmp_path, "DSC00002.ARW", MediaType.RAW)
    _make_record(tmp_path, "C0001.MP4", MediaType.VIDEO)

    results = search_history(query="DSC")
    assert len(results) == 2
    assert all("DSC" in Path(r.source_path).name for r in results)


def test_search_by_filename_case_insensitive(tmp_path):
    _make_record(tmp_path, "IMG_0001.JPG")
    results = search_history(query="img_0001")
    assert len(results) == 1


def test_search_no_match_returns_empty(tmp_path):
    _make_record(tmp_path, "DSC00001.ARW", MediaType.RAW)
    results = search_history(query="NOTHING_MATCHES_THIS")
    assert results == []


def test_search_empty_query_returns_all(tmp_path):
    _make_record(tmp_path, "A.JPG")
    _make_record(tmp_path, "B.JPG")
    results = search_history(query="")
    assert len(results) == 2


# ---------------------------------------------------------------------------
# search_history — camera filter
# ---------------------------------------------------------------------------

def test_search_by_camera(tmp_path):
    _make_record(tmp_path, "A.ARW", camera_make="Sony", camera_model="ILCE-6300")
    _make_record(tmp_path, "B.CR3", camera_make="Canon", camera_model="EOS R5")

    results = search_history(camera="Sony")
    assert len(results) == 1
    assert results[0].camera_make == "Sony"


def test_search_by_camera_model(tmp_path):
    _make_record(tmp_path, "A.ARW", camera_make="Sony", camera_model="ILCE-6300")
    _make_record(tmp_path, "B.ARW", camera_make="Sony", camera_model="ILCE-7M4")

    results = search_history(camera="ILCE-7M4")
    assert len(results) == 1
    assert results[0].camera_model == "ILCE-7M4"


def test_search_camera_no_match(tmp_path):
    _make_record(tmp_path, "A.ARW", camera_make="Sony", camera_model="ILCE-6300")
    results = search_history(camera="Nikon")
    assert results == []


# ---------------------------------------------------------------------------
# search_history — media type filter
# ---------------------------------------------------------------------------

def test_search_by_media_type_photo(tmp_path):
    _make_record(tmp_path, "A.JPG", MediaType.PHOTO)
    _make_record(tmp_path, "B.ARW", MediaType.RAW)
    _make_record(tmp_path, "C.MP4", MediaType.VIDEO)

    results = search_history(media_type="photo")
    assert len(results) == 1
    assert results[0].media_type == "photo"


def test_search_by_media_type_raw(tmp_path):
    _make_record(tmp_path, "A.ARW", MediaType.RAW)
    _make_record(tmp_path, "B.MP4", MediaType.VIDEO)

    results = search_history(media_type="raw")
    assert len(results) == 1
    assert results[0].media_type == "raw"


def test_search_by_media_type_video(tmp_path):
    _make_record(tmp_path, "A.JPG", MediaType.PHOTO)
    _make_record(tmp_path, "B.MP4", MediaType.VIDEO)

    results = search_history(media_type="video")
    assert len(results) == 1
    assert results[0].media_type == "video"


# ---------------------------------------------------------------------------
# search_history — date range filter
# ---------------------------------------------------------------------------

def test_search_by_date_from(tmp_path):
    _make_record(tmp_path, "OLD.JPG", captured_at=datetime(2025, 1, 1))
    _make_record(tmp_path, "NEW.JPG", captured_at=datetime(2026, 4, 1))

    results = search_history(date_from=datetime(2026, 1, 1))
    assert len(results) == 1
    assert "NEW" in Path(results[0].source_path).name


def test_search_by_date_to(tmp_path):
    _make_record(tmp_path, "OLD.JPG", captured_at=datetime(2025, 1, 1))
    _make_record(tmp_path, "NEW.JPG", captured_at=datetime(2026, 4, 1))

    results = search_history(date_to=datetime(2025, 12, 31))
    assert len(results) == 1
    assert "OLD" in Path(results[0].source_path).name


def test_search_by_date_range(tmp_path):
    _make_record(tmp_path, "A.JPG", captured_at=datetime(2025, 1, 1))
    _make_record(tmp_path, "B.JPG", captured_at=datetime(2026, 3, 1))
    _make_record(tmp_path, "C.JPG", captured_at=datetime(2026, 4, 7))

    results = search_history(
        date_from=datetime(2026, 1, 1),
        date_to=datetime(2026, 4, 6),
    )
    assert len(results) == 1
    assert "B" in Path(results[0].source_path).name


# ---------------------------------------------------------------------------
# search_history — combined filters
# ---------------------------------------------------------------------------

def test_search_combined_query_and_type(tmp_path):
    _make_record(tmp_path, "DSC001.ARW", MediaType.RAW)
    _make_record(tmp_path, "DSC002.JPG", MediaType.PHOTO)
    _make_record(tmp_path, "C0001.MP4",  MediaType.VIDEO)

    results = search_history(query="DSC", media_type="raw")
    assert len(results) == 1
    assert results[0].media_type == "raw"


def test_search_combined_camera_and_type(tmp_path):
    _make_record(tmp_path, "A.ARW", MediaType.RAW,   camera_make="Sony",  camera_model="ILCE-6300")
    _make_record(tmp_path, "B.JPG", MediaType.PHOTO, camera_make="Sony",  camera_model="ILCE-6300")
    _make_record(tmp_path, "C.CR3", MediaType.RAW,   camera_make="Canon", camera_model="EOS R5")

    results = search_history(camera="Sony", media_type="raw")
    assert len(results) == 1
    assert results[0].camera_make == "Sony"
    assert results[0].media_type == "raw"


# ---------------------------------------------------------------------------
# get_distinct_cameras
# ---------------------------------------------------------------------------

def test_get_distinct_cameras_returns_sorted(tmp_path):
    _make_record(tmp_path, "A.JPG", camera_make="Sony",  camera_model="ILCE-6300")
    _make_record(tmp_path, "B.CR3", camera_make="Canon", camera_model="EOS R5")

    cameras = get_distinct_cameras()
    assert "Sony ILCE-6300" in cameras
    assert "Canon EOS R5" in cameras
    assert cameras == sorted(cameras)


def test_get_distinct_cameras_deduplicates(tmp_path):
    _make_record(tmp_path, "A.JPG", camera_make="Sony", camera_model="ILCE-6300")
    _make_record(tmp_path, "B.ARW", camera_make="Sony", camera_model="ILCE-6300")

    cameras = get_distinct_cameras()
    assert cameras.count("Sony ILCE-6300") == 1


def test_get_distinct_cameras_empty_db():
    cameras = get_distinct_cameras()
    assert cameras == []


def test_get_distinct_cameras_skips_null_make(tmp_path):
    _make_record(tmp_path, "A.JPG", camera_make="", camera_model="")
    cameras = get_distinct_cameras()
    assert cameras == []
