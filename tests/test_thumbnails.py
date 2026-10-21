"""Tests for thumbnail generation."""

import io
from pathlib import Path

import pytest
from PIL import Image

import backend.core.thumbnails as thumbs
from backend.core.models import MediaType


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "_CACHE_DIR", tmp_path / "cache")


def _jpeg(size=(1200, 800), color=(200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def _size_of(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def test_photo_thumbnail_is_small(tmp_path):
    src = tmp_path / "IMG001.JPG"
    src.write_bytes(_jpeg())
    data = thumbs.thumbnail(src, MediaType.PHOTO)
    assert data is not None
    w, h = _size_of(data)
    assert max(w, h) <= thumbs.THUMB_SIZE
    assert w > h   # aspect preserved


def test_thumbnail_is_cached(tmp_path, monkeypatch):
    src = tmp_path / "IMG001.JPG"
    src.write_bytes(_jpeg())
    first = thumbs.thumbnail(src, MediaType.PHOTO)
    assert list((tmp_path / "cache").rglob("*.jpg"))

    def _fail(*_a, **_kw):
        raise AssertionError("thumbnail was regenerated instead of read from cache")
    monkeypatch.setattr(thumbs, "_generate", _fail)
    assert thumbs.thumbnail(src, MediaType.PHOTO) == first


def test_raw_fallback_finds_embedded_jpeg(tmp_path):
    # Unknown RAW container: some header bytes, then an embedded preview
    raw = tmp_path / "IMG_0001.CR3"
    raw.write_bytes(b"\x00\x00\x00\x18ftypcrx " + b"\x00" * 500 + _jpeg((800, 600)) + b"\x00" * 100)
    data = thumbs.thumbnail(raw, MediaType.RAW)
    assert data is not None
    assert max(_size_of(data)) <= thumbs.THUMB_SIZE


def test_video_uses_sony_thmbnl(tmp_path):
    clip_dir = tmp_path / "PRIVATE" / "M4ROOT" / "CLIP"
    thumb_dir = tmp_path / "PRIVATE" / "M4ROOT" / "THMBNL"
    clip_dir.mkdir(parents=True)
    thumb_dir.mkdir(parents=True)
    clip = clip_dir / "C0001.MP4"
    clip.write_bytes(b"\x00" * 1000)
    (thumb_dir / "C0001T01.JPG").write_bytes(_jpeg((640, 360)))
    assert thumbs.thumbnail(clip, MediaType.VIDEO) is not None


def test_video_uses_thm_sidecar(tmp_path):
    clip = tmp_path / "GX010001.MP4"
    clip.write_bytes(b"\x00" * 1000)
    (tmp_path / "GX010001.THM").write_bytes(_jpeg((320, 240)))
    assert thumbs.thumbnail(clip, MediaType.VIDEO) is not None


def test_video_without_companion_returns_none(tmp_path):
    clip = tmp_path / "C0001.MP4"
    clip.write_bytes(b"\x00" * 1000)
    assert thumbs.thumbnail(clip, MediaType.VIDEO) is None


def test_unreadable_file_returns_none(tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    assert thumbs.thumbnail(bad, MediaType.PHOTO) is None
    assert thumbs.thumbnail(tmp_path / "missing.jpg", MediaType.PHOTO) is None
