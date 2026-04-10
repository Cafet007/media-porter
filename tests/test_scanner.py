"""Tests for backend/core/scanner.py"""

import tempfile
from pathlib import Path

import pytest

from backend.core.models import MediaType
from backend.core.scanner import ScanResult, scan, scan_card


@pytest.fixture()
def fake_sd(tmp_path: Path) -> Path:
    """Create a fake SD card DCIM structure."""
    dcim = tmp_path / "DCIM" / "100CANON"
    dcim.mkdir(parents=True)

    (dcim / "IMG_0001.JPG").write_bytes(b"fake-jpeg")
    (dcim / "IMG_0002.CR3").write_bytes(b"fake-raw")
    (dcim / "MVI_0003.MP4").write_bytes(b"fake-video")
    (dcim / ".DS_Store").write_bytes(b"system")
    (dcim / "THUMB.THM").write_bytes(b"thumbnail")

    return tmp_path


def test_scan_counts(fake_sd: Path) -> None:
    result = scan(fake_sd)
    assert result.total == 3
    assert len(result.photos) == 1
    assert len(result.raws) == 1
    assert len(result.videos) == 1


def test_scan_skips_system_files(fake_sd: Path) -> None:
    result = scan(fake_sd)
    names = [f.name for f in result.files]
    assert ".DS_Store" not in names
    assert "THUMB.THM" not in names


def test_scan_summary(fake_sd: Path) -> None:
    result = scan(fake_sd)
    summary = result.summary()
    assert "3 files" in summary
    assert "1 photos" in summary
    assert "1 RAW" in summary
    assert "1 videos" in summary


def test_scan_progress_callback(fake_sd: Path) -> None:
    calls: list[tuple[int, int]] = []

    def cb(done: int, total: int, path: Path) -> None:
        calls.append((done, total))

    scan(fake_sd, progress_cb=cb)
    assert len(calls) > 0


def test_scan_nonexistent_raises() -> None:
    with pytest.raises(FileNotFoundError):
        scan("/nonexistent/path")


def test_scan_file_not_dir_raises(tmp_path: Path) -> None:
    f = tmp_path / "file.jpg"
    f.write_bytes(b"x")
    with pytest.raises(NotADirectoryError):
        scan(f)


# ---------------------------------------------------------------------------
# roots_scanned — per-folder diagnostics
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_sony_sd(tmp_path: Path) -> Path:
    """Sony A6300-style SD card: photos in DCIM, videos in PRIVATE/M4ROOT/CLIP."""
    dcim = tmp_path / "DCIM" / "100MSDCF"
    dcim.mkdir(parents=True)
    (dcim / "DSC00001.ARW").write_bytes(b"raw")
    (dcim / "DSC00001.JPG").write_bytes(b"jpg")

    clip = tmp_path / "PRIVATE" / "M4ROOT" / "CLIP"
    clip.mkdir(parents=True)
    (clip / "C0001.MP4").write_bytes(b"video")
    (clip / "C0002.MP4").write_bytes(b"video2")

    return tmp_path


def test_scan_card_roots_scanned_sony(fake_sony_sd: Path) -> None:
    result = scan_card(fake_sony_sd)
    assert result.roots_scanned, "roots_scanned should not be empty"
    total = sum(result.roots_scanned.values())
    assert total == result.total


def test_scan_card_roots_scanned_has_both_sony_roots(fake_sony_sd: Path) -> None:
    result = scan_card(fake_sony_sd)
    root_names = {r.name for r in result.roots_scanned}
    # Sony cards should have both DCIM and PRIVATE as scan roots
    assert "DCIM" in root_names
    assert "PRIVATE" in root_names


def test_scan_card_roots_scanned_counts_per_root(fake_sony_sd: Path) -> None:
    result = scan_card(fake_sony_sd)
    by_name = {r.name: count for r, count in result.roots_scanned.items()}
    assert by_name["DCIM"] == 2    # ARW + JPG
    assert by_name["PRIVATE"] == 2  # two MP4s


def test_scan_card_generic_has_dcim_root(tmp_path: Path) -> None:
    """Generic camera (e.g. Canon/Nikon fallback) — DCIM only."""
    dcim = tmp_path / "DCIM" / "100CANON"
    dcim.mkdir(parents=True)
    (dcim / "IMG001.JPG").write_bytes(b"jpg")
    (dcim / "IMG001.CR3").write_bytes(b"raw")

    result = scan_card(tmp_path)
    assert sum(result.roots_scanned.values()) == result.total
    root_names = {r.name for r in result.roots_scanned}
    assert "DCIM" in root_names


def test_scan_result_roots_scanned_default_empty() -> None:
    result = ScanResult(files=[])
    assert result.roots_scanned == {}
