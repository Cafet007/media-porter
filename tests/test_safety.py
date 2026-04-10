"""Tests for the safety guard."""

import pytest
from pathlib import Path
from backend.core.safety import (
    protect, unprotect, is_protected,
    guard_write, guard_delete, guard_same_path, guard_space,
    cleanup_temp_files,
    SafetyError, _protected_roots,
)


@pytest.fixture(autouse=True)
def clear_protected():
    """Reset protected paths between tests."""
    _protected_roots.clear()
    yield
    _protected_roots.clear()


def test_protect_blocks_write(tmp_path):
    protect(tmp_path)
    with pytest.raises(SafetyError, match="WRITE BLOCKED"):
        guard_write(tmp_path / "photo.arw")


def test_protect_blocks_nested_write(tmp_path):
    protect(tmp_path)
    with pytest.raises(SafetyError, match="WRITE BLOCKED"):
        guard_write(tmp_path / "DCIM" / "100MSDCF" / "photo.arw")


def test_unprotected_path_allows_write(tmp_path):
    # Should not raise
    guard_write(tmp_path / "output" / "photo.arw")


def test_delete_always_blocked(tmp_path):
    with pytest.raises(SafetyError, match="DELETE BLOCKED"):
        guard_delete(tmp_path / "photo.arw")


def test_delete_blocked_even_on_unprotected(tmp_path):
    # Deletion is NEVER allowed, regardless of protection
    with pytest.raises(SafetyError, match="DELETE BLOCKED"):
        guard_delete(tmp_path / "anything.jpg")


def test_same_path_blocked(tmp_path):
    f = tmp_path / "photo.arw"
    with pytest.raises(SafetyError, match="SOURCE == DESTINATION"):
        guard_same_path(f, f)


def test_different_paths_allowed(tmp_path):
    src = tmp_path / "src" / "photo.arw"
    dst = tmp_path / "dst" / "photo.arw"
    guard_same_path(src, dst)  # should not raise


def test_is_protected_true(tmp_path):
    protect(tmp_path)
    assert is_protected(tmp_path / "DCIM" / "file.arw")


def test_is_protected_false(tmp_path):
    other = tmp_path / "other"
    assert not is_protected(other / "file.arw")


# ---------------------------------------------------------------------------
# cleanup_temp_files
# ---------------------------------------------------------------------------

def test_cleanup_removes_temp_files(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / ".mporter_tmp_abc123").write_bytes(b"partial")
    (dest / ".mporter_tmp_xyz789").write_bytes(b"partial2")
    (dest / "real_file.jpg").write_bytes(b"real")

    removed = cleanup_temp_files(dest)

    assert removed == 2
    assert not (dest / ".mporter_tmp_abc123").exists()
    assert not (dest / ".mporter_tmp_xyz789").exists()
    assert (dest / "real_file.jpg").exists()  # real file untouched


def test_cleanup_recurses_into_subdirs(tmp_path):
    dest = tmp_path / "dest"
    sub = dest / "JPG" / "2026-04-07"
    sub.mkdir(parents=True)
    (sub / ".mporter_tmp_deep").write_bytes(b"partial")

    removed = cleanup_temp_files(dest)
    assert removed == 1
    assert not (sub / ".mporter_tmp_deep").exists()


def test_cleanup_nonexistent_dir_is_safe(tmp_path):
    removed = cleanup_temp_files(tmp_path / "does_not_exist")
    assert removed == 0


def test_cleanup_returns_zero_when_no_temps(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "IMG001.jpg").write_bytes(b"real")
    removed = cleanup_temp_files(dest)
    assert removed == 0
