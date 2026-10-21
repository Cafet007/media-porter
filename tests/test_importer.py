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


def _make_nested_file(
    src_dir: Path,
    folder: str,
    name: str,
    media_type: MediaType = MediaType.PHOTO,
    content: bytes = b"x" * 64,
) -> MediaFile:
    directory = src_dir / folder
    directory.mkdir()
    path = directory / name
    path.write_bytes(content)
    f = MediaFile(path=path, media_type=media_type, size=len(content))
    f.captured_at = datetime(2026, 3, 24, 10, 0)
    return f


@pytest.fixture()
def src(tmp_path: Path) -> Path:
    d = tmp_path / "SD"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Keep importer tests away from the user's real import history."""
    import backend.db.models as db_models
    import backend.db.repository as db_repo

    monkeypatch.setattr(db_models, "_DB_PATH", tmp_path / "test_history.db")
    db_repo._engine = None
    yield
    db_repo._engine = None


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


def test_run_import_conflicts_batch_collision_without_counter(src, config):
    files = [
        _make_nested_file(src, "a", "IMG001.JPG", content=b"a" * 64),
        _make_nested_file(src, "b", "IMG001.JPG", content=b"b" * 64),
    ]

    result = run_import(files, config)

    assert result.total_copied == 1
    assert result.total_conflicts == 1


def test_run_import_uses_counter_template_for_batch_collision(src, config):
    config.templates["photo"] = "JPG/{date}/{original_name}_{counter}.{ext}"
    files = [
        _make_nested_file(src, "a", "IMG001.JPG", content=b"a" * 64),
        _make_nested_file(src, "b", "IMG001.JPG", content=b"b" * 64),
    ]

    result = run_import(files, config)

    assert result.total_copied == 2
    copied_names = {dest.name for _, dest in result.copied}
    assert copied_names == {"IMG001_001.jpg", "IMG001_002.jpg"}


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


def test_run_import_calls_verify_progress(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO)
    calls = []

    def cb(name, bytes_done, bytes_total):
        calls.append((name, bytes_done, bytes_total))

    run_import([f], config, verify_progress_cb=cb)
    assert calls
    assert calls[-1] == ("IMG001.JPG", f.size_bytes, f.size_bytes)


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

def test_run_import_skips_via_db_path_when_recorded_dest_exists(src, config):
    """DB history can skip if the old destination still exists under previous rules."""
    f = _make_file(src, "IMG_DB.JPG", MediaType.PHOTO, size=64)

    # First import — copies and records in DB
    result1 = run_import([f], config)
    assert result1.total_copied == 1

    # Change rules so filesystem dedup at the newly resolved destination
    # would miss the previous import, but DB history still points at an
    # existing destination file.
    config.templates["photo"] = "NewRules/{date}/{original_name}.{ext}"
    f2 = _make_file(src, "IMG_DB.JPG", MediaType.PHOTO, size=64)
    result2 = run_import([f2], config)
    assert result2.total_skipped == 1
    assert result2.total_copied  == 0


def test_run_import_reimports_when_recorded_dest_was_deleted(src, config):
    f = _make_file(src, "IMG_DELETED.JPG", MediaType.PHOTO, size=64)

    result1 = run_import([f], config)
    assert result1.total_copied == 1
    result1.copied[0][1].unlink()

    f2 = _make_file(src, "IMG_DELETED.JPG", MediaType.PHOTO, size=64)
    result2 = run_import([f2], config)
    assert result2.total_copied == 1
    assert result2.total_skipped == 0


def test_run_import_does_not_skip_reused_source_path_with_new_capture_date(src, config):
    f = _make_file(src, "IMG_REUSE.JPG", MediaType.PHOTO, size=64)

    result1 = run_import([f], config)
    assert result1.total_copied == 1

    copied_path = result1.copied[0][1]
    copied_path.unlink()

    f2 = _make_file(src, "IMG_REUSE.JPG", MediaType.PHOTO, size=64)
    f2.captured_at = datetime(2026, 3, 25, 10, 0)

    result2 = run_import([f2], config)
    assert result2.total_copied == 1
    assert result2.total_skipped == 0


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


def test_run_import_reports_verify_failure_and_does_not_record(src, config, monkeypatch):
    import backend.core.importer as importer
    from backend.db.repository import is_path_imported

    monkeypatch.setattr(importer, "verify_copy", lambda *a, **kw: False)
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO)
    verified = []
    result = run_import([f], config, verify_cb=lambda name, ok: verified.append((name, ok)))

    assert result.total_copied        == 1
    assert result.total_verify_failed == 1
    assert result.total_verified      == 0
    assert result.total_failed        == 0
    assert verified == [("IMG001.JPG", False)]
    # A bad copy must not count as imported, or the next run would skip it
    assert not is_path_imported(f.path)


def test_run_import_cleans_stale_temp_in_dest_folder(src, config):
    f = _make_file(src, "IMG001.JPG", MediaType.PHOTO)
    dest_dir = config.photo_base / "JPG" / "2026-03-24"
    dest_dir.mkdir(parents=True)
    stale = dest_dir / ".mporter_tmp_crashed"
    stale.write_bytes(b"partial")

    run_import([f], config)
    assert not stale.exists()
