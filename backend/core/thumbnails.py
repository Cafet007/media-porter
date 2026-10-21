"""
Thumbnails — small JPEG previews for the file browser.

Never decodes full-resolution images:
  JPG/TIFF/PNG → Pillow draft mode (decodes at 1/2–1/8 scale)
  RAW          → the JPEG preview the camera already embedded in the file
  Video        → the camera's own thumbnail file next to the clip
                 (Sony THMBNL/…T01.JPG, GoPro/Canon .THM, …) when present

Results are cached on the internal drive at ~/.media-porter/thumbs, keyed by
path + size + mtime, so re-inserting the same card is instant. Source files
are only ever opened read-only.
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

from .models import MediaType

logger = logging.getLogger(__name__)

THUMB_SIZE = 480           # longest edge of cached thumbnails (px) — sharp on Retina grid cards
_CACHE_DIR = Path.home() / ".media-porter" / "thumbs"
_RAW_SCAN_BYTES = 4 * 1024 * 1024   # fallback: look for an embedded JPEG in this window
_MAX_PREVIEW_BYTES = 16 * 1024 * 1024

# EXIF orientation → PIL transpose operation
_ORIENTATION_OPS = {2: "FLIP_LEFT_RIGHT", 3: "ROTATE_180", 4: "FLIP_TOP_BOTTOM",
                    5: "TRANSPOSE", 6: "ROTATE_270", 7: "TRANSVERSE", 8: "ROTATE_90"}


def thumbnail(path: Path, media_type: MediaType, *, use_cache: bool = True) -> bytes | None:
    """
    Return JPEG bytes for a thumbnail of `path`, or None if no preview is
    available (e.g. a video with no camera thumbnail). Never raises.
    """
    try:
        cache_path = _cache_path(path) if use_cache else None
        if cache_path is not None and cache_path.exists():
            return cache_path.read_bytes()

        data = _generate(path, media_type)
        if data and cache_path is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_path.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(cache_path)
            except OSError as e:
                logger.debug("Thumbnail cache write failed for %s: %s", path, e)
        return data
    except Exception as e:
        logger.debug("Thumbnail failed for %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _generate(path: Path, media_type: MediaType) -> bytes | None:
    if media_type == MediaType.PHOTO:
        return _from_image_bytes(None, path)
    if media_type == MediaType.RAW:
        preview, orientation = _raw_preview(path)
        return _from_image_bytes(preview, None, orientation=orientation) if preview else None
    if media_type == MediaType.VIDEO:
        companion = _video_companion(path)
        return _from_image_bytes(None, companion) if companion else None
    return None


def _from_image_bytes(data: bytes | None, path: Path | None, *, orientation: int = 0) -> bytes | None:
    """Decode (in draft mode), orient, shrink and re-encode as a small JPEG."""
    from PIL import Image, ImageOps

    source = io.BytesIO(data) if data is not None else path
    if source is None:
        return None
    with Image.open(source) as img:
        img.draft("RGB", (THUMB_SIZE, THUMB_SIZE))   # JPEG: decode at reduced scale
        if orientation:
            op = _ORIENTATION_OPS.get(orientation)
            img = img.transpose(getattr(Image.Transpose, op)) if op else img
        else:
            img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((THUMB_SIZE, THUMB_SIZE))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=82)
        return out.getvalue()


def _raw_preview(path: Path) -> tuple[bytes | None, int]:
    """
    Return (embedded JPEG preview, EXIF orientation) for a RAW file.

    TIFF-based RAWs (ARW, NEF, CR2, DNG, ORF, PEF, …) store one or more
    previews referenced by JPEGInterchangeFormat/Length tag pairs — pick the
    largest. Otherwise (CR3, RAF, …) look for the first JPEG near the start.
    """
    orientation = 0
    best: tuple[int, int] | None = None   # (offset, length)
    try:
        import exifread
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False, extract_thumbnail=True)
        orient = tags.get("Image Orientation")
        if orient is not None:
            try:
                orientation = int(orient.values[0])
            except (AttributeError, IndexError, TypeError, ValueError):
                orientation = 0

        for name, tag in tags.items():
            if not name.endswith("JPEGInterchangeFormat"):
                continue
            length_tag = tags.get(name + "Length")
            try:
                offset = int(str(tag))
                length = int(str(length_tag)) if length_tag is not None else 0
            except ValueError:
                continue
            if 0 < length <= _MAX_PREVIEW_BYTES and (best is None or length > best[1]):
                best = (offset, length)

        if best is None and tags.get("JPEGThumbnail"):
            return bytes(tags["JPEGThumbnail"]), orientation
    except Exception as e:
        logger.debug("EXIF preview lookup failed for %s: %s", path, e)

    with open(path, "rb") as fh:
        if best is not None:
            fh.seek(best[0])
            data = fh.read(best[1])
            if data[:2] == b"\xff\xd8":
                return data, orientation
            fh.seek(0)
        window = fh.read(_RAW_SCAN_BYTES)

    start = window.find(b"\xff\xd8\xff", 1)   # skip a JPEG-at-offset-0 false positive
    if start == -1:
        return None, orientation
    return window[start:], orientation


def _video_companion(path: Path) -> Path | None:
    """Camera-written thumbnail for a video clip, if the card has one."""
    stem = path.stem
    candidates = [
        # Sony: PRIVATE/M4ROOT/CLIP/C0001.MP4 → PRIVATE/M4ROOT/THMBNL/C0001T01.JPG
        path.parent.parent / "THMBNL" / f"{stem}T01.JPG",
        # GoPro / Canon: GX010001.THM, MVI_0001.THM
        path.with_suffix(".THM"),
        path.with_suffix(".thm"),
        # Sony (older): CLIP/C0001.JPG
        path.with_suffix(".JPG"),
        path.with_suffix(".jpg"),
    ]
    for candidate in candidates:
        if candidate != path and candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(path: Path) -> Path:
    st = path.stat()
    key = f"{path}|{st.st_size}|{int(st.st_mtime)}|{THUMB_SIZE}"
    digest = hashlib.sha1(key.encode("utf-8", "surrogateescape")).hexdigest()
    return _CACHE_DIR / digest[:2] / f"{digest}.jpg"
