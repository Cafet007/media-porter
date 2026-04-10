"""Tests for backend/core/report.py"""

import csv
from datetime import datetime
from pathlib import Path

import pytest

from backend.core.importer import ImportResult
from backend.core.models import MediaFile, MediaType
from backend.core.report import write_report


def _file(tmp_path: Path, name: str, media_type=MediaType.PHOTO, size=64) -> MediaFile:
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    f = MediaFile(path=p, media_type=media_type, size=size)
    f.captured_at = datetime(2026, 4, 7, 10, 0)
    return f


@pytest.fixture()
def src(tmp_path):
    d = tmp_path / "SD"
    d.mkdir()
    return d


@pytest.fixture()
def report_dir(tmp_path):
    d = tmp_path / "reports"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# write_report — file creation
# ---------------------------------------------------------------------------

def test_write_report_creates_file(src, report_dir):
    result = ImportResult()
    f = _file(src, "IMG001.JPG")
    result.copied.append((f, Path("/dest/IMG001.JPG")))
    result.verified.append(f)

    path = write_report(result, report_dir)
    assert path.exists()
    assert path.suffix == ".csv"


def test_write_report_uses_session_name(src, report_dir):
    result = ImportResult()
    path = write_report(result, report_dir, session_name="wedding_2026")
    assert "wedding_2026" in path.name


def test_write_report_creates_dir_if_missing(src, tmp_path):
    new_dir = tmp_path / "new" / "nested"
    result = ImportResult()
    path = write_report(result, new_dir)
    assert path.exists()


# ---------------------------------------------------------------------------
# CSV content — copied files
# ---------------------------------------------------------------------------

def test_report_copied_row(src, report_dir):
    result = ImportResult()
    f = _file(src, "IMG001.JPG")
    dest = Path("/dest/Photos/2026-04-07/IMG001.JPG")
    result.copied.append((f, dest))
    result.verified.append(f)

    path = write_report(result, report_dir)
    rows = _read_csv(path)

    assert len(rows) == 1
    assert rows[0]["filename"] == "IMG001.JPG"
    assert rows[0]["status"] == "Copied"
    assert rows[0]["verified"] == "Yes"
    assert rows[0]["dest_path"] == str(dest)


def test_report_copied_not_verified(src, report_dir):
    result = ImportResult()
    f = _file(src, "IMG001.JPG")
    result.copied.append((f, Path("/dest/IMG001.JPG")))
    # NOT added to result.verified

    path = write_report(result, report_dir)
    rows = _read_csv(path)
    assert rows[0]["verified"] == "No"


# ---------------------------------------------------------------------------
# CSV content — skipped / conflict / failed
# ---------------------------------------------------------------------------

def test_report_skipped_row(src, report_dir):
    result = ImportResult()
    f = _file(src, "IMG002.JPG")
    result.skipped.append(f)

    rows = _read_csv(write_report(result, report_dir))
    assert rows[0]["status"] == "Skipped"
    assert rows[0]["verified"] == "N/A"
    assert rows[0]["dest_path"] == ""


def test_report_conflict_row(src, report_dir):
    result = ImportResult()
    f = _file(src, "IMG003.JPG")
    result.conflicts.append(f)

    rows = _read_csv(write_report(result, report_dir))
    assert rows[0]["status"] == "Conflict"
    assert rows[0]["verified"] == "N/A"


def test_report_failed_row(src, report_dir):
    result = ImportResult()
    f = _file(src, "IMG004.JPG")
    result.failed.append((f, "disk full"))

    rows = _read_csv(write_report(result, report_dir))
    assert rows[0]["status"] == "Failed: disk full"
    assert rows[0]["verified"] == "N/A"


# ---------------------------------------------------------------------------
# CSV content — mixed result
# ---------------------------------------------------------------------------

def test_report_mixed_result(src, report_dir):
    result = ImportResult()
    copied = _file(src, "A.JPG")
    skipped = _file(src, "B.JPG")
    failed = _file(src, "C.JPG")

    result.copied.append((copied, Path("/dest/A.JPG")))
    result.verified.append(copied)
    result.skipped.append(skipped)
    result.failed.append((failed, "read error"))

    rows = _read_csv(write_report(result, report_dir))
    assert len(rows) == 3
    statuses = {r["status"] for r in rows}
    assert "Copied" in statuses
    assert "Skipped" in statuses
    assert any("Failed" in s for s in statuses)


def test_report_empty_result(report_dir):
    result = ImportResult()
    rows = _read_csv(write_report(result, report_dir))
    assert rows == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
