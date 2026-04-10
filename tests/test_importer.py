"""Tests for backend/core/importer.py — run_import() integration tests."""

import threading
from datetime import datetime
from pathlib import Path

import pytest

from backend.core.importer import ImportResult, run_import
from backend.core.models import MediaFile, MediaType
from backend.core.rules import DestinationConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(
    src_dir: Path,
    name: str,
    media_type: MediaType = MediaType.PHOTO,
    size: int = 64,
) -> MediaFile:
    path = src_dir / name
    path.write_bytes(b"x" * size)
    f = MediaFile(path=path, media_type=media_type, size=size)
    f.captured_at = datetime(2026, 3, 24, 10, 0)
    return f


@pytest.fixture()
def src(tmp_path: Path) -> Path:
    d = tmp_path / "SD"
    d.mkdir()
    return d


@pytest.fixture()
def config(tmp_path: Path) -> DestinationConfig:
    return DestinationConfig(
        photo_base=tmp_path / "Photography",
        video_base=tmp_path / "Footage",
    )


# ---------------------------------------------------------------------------
# ImportResult
# ---------------------------------------------------------------------------

def test_import_result_totals():
    r = ImportResult()
    assert r.total_copied    == 0
    assert r.total_skipped   == 0
    assert r.total_conflicts == 0
    assert r.total_failed    == 0


def test_import_result_summary_basic():
    r = ImportResult()
    summary = r.summary()
    assert "Copied 0" in summary
    assert "Skipped 0" in summary


def test_import_result_summary_with_conflicts():
    from backend.core.models import MediaFile
    r = ImportResult()
    f = MediaFile(path=Path("x.jpg"), media_type=MediaType.PHOTO, size=1)
    r.conflicts.append(f)
    assert "Conflicts 1" in r.summary()


def test_import_result_summary_no_failed_line_when_zero():
    r = ImportResult()
    assert "Failed" not in r.summary()


# ---------------------------------------------------------------------------
# run_import — basic copy
# ---------------------------------------------------------------------------

def test_run_import_copies_file(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO)
    result = run_import([f], config)

    assert result.total_copied  == 1
    assert result.total_skipped == 0
    assert result.total_failed  == 0

    copied_path = result.copied[0][1]
    assert copied_path.exists()
    assert copied_path.read_bytes() == b"x" * 64


def test_run_import_copies_raw(src, config):
    f = _make_file(src, "DSC001.ARW", MediaType.RAW)
    result = run_import([f], config)
    assert result.total_copied == 1
    dest = result.copied[0][1]
    assert "RAW" in str(dest)


def test_run_import_copies_video(src, config):
    f = _make_file(src, "C0001.MP4", MediaType.VIDEO)
    result = run_import([f], config)
    assert result.total_copied == 1
    dest = result.copied[0][1]
    assert str(dest).startswith(str(config.video_base))


def test_run_import_multiple_files(src, config):
    files = [
        _make_file(src, "IMG001.JPG", MediaType.PHOTO),
        _make_file(src, "DSC001.ARW", MediaType.RAW),
        _make_file(src, "C0001.MP4",  MediaType.VIDEO),
    ]
    result = run_import(files, config)
    assert result.total_copied == 3


# ---------------------------------------------------------------------------
# Dedup — skip already imported
# ---------------------------------------------------------------------------

def test_run_import_skips_existing(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO, size=128)
    # Pre-populate dest to simulate previous import
    dest_dir = config.photo_base / "JPG" / "2026-03-24"
    dest_dir.mkdir(parents=True)
    (dest_dir / "IMG001.JPG").write_bytes(b"x" * 128)

    result = run_import([f], config)
    assert result.total_copied  == 0
    assert result.total_skipped == 1


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

def test_run_import_calls_progress(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO)
    calls = []

    def cb(done, total, name, bytes_done, bytes_total, file_bytes_done, file_bytes_total):
        calls.append((done, total, name))

    run_import([f], config, progress_cb=cb)
    assert len(calls) > 0
    assert all(name == "IMG001.JPG" for _, _, name in calls)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_run_import_cancel_before_start(src, config):
    files = [_make_file(src, f"IMG00{i}.JPG", MediaType.PHOTO) for i in range(5)]
    cancel = threading.Event()
    cancel.set()  # cancel immediately

    result = run_import(files, config, cancel_event=cancel)
    assert result.total_copied == 0


# ---------------------------------------------------------------------------
# SHA256 hash stored on file
# ---------------------------------------------------------------------------

def test_run_import_stores_hash(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO)
    run_import([f], config)
    assert f.file_hash is not None
    assert len(f.file_hash) == 64  # SHA256 hex = 64 chars


# ---------------------------------------------------------------------------
# Conflict — destination exists but not in dedup index
# ---------------------------------------------------------------------------

def test_run_import_skips_via_db_path(tmp_path, src, config, monkeypatch):
    """Files previously recorded in the DB by source path are skipped even if dest was moved."""
    # Use an isolated DB so hash collisions from the real user DB can't interfere
    import backend.db.models as db_models
    import backend.db.repository as db_repo

    test_db = tmp_path / "test_history.db"
    monkeypatch.setattr(db_models, "_DB_PATH", test_db)
    db_repo._engine = None  # force re-init with new path

    f = _make_file(src, "IMG_DB.JPG", MediaType.PHOTO, size=64)

    # First import — copies and records in DB
    result1 = run_import([f], config)
    assert result1.total_copied == 1

    # Simulate dest being reorganized: delete the copied file from disk
    copied_path = result1.copied[0][1]
    copied_path.unlink()

    # Second import — filesystem dedup won't find it (file is gone),
    # but DB-path dedup should skip it
    f2 = _make_file(src, "IMG_DB.JPG", MediaType.PHOTO, size=64)
    result2 = run_import([f2], config)
    assert result2.total_skipped == 1
    assert result2.total_copied  == 0

    # Cleanup: reset engine so subsequent tests use the real DB
    db_repo._engine = None


def test_run_import_conflict_when_dest_exists(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO, size=64)

    # Place a file at the destination with a DIFFERENT size (bypasses dedup)
    # but exists at the exact resolved dest path (triggers DESTINATION EXISTS)
    dest_dir = config.photo_base / "JPG" / "2026-03-24"
    dest_dir.mkdir(parents=True)
    (dest_dir / "IMG001.jpg").write_bytes(b"y" * 999)  # different size → not deduped

    result = run_import([f], config)
    assert result.total_conflicts == 1
    assert result.total_failed    == 0
