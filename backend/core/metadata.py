"""
Metadata extractor — enriches MediaFile objects with EXIF (photos/RAW)
and container metadata (videos).

Dependencies:
    pip install Pillow exifread pymediainfo
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import MediaFile, MediaType

logger = logging.getLogger(__name__)

# strptime formats tried in order for EXIF date strings
_EXIF_DATE_FORMATS = [
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d %H:%M:%S%z",
]


def extract(file: MediaFile) -> MediaFile:
    """
    Populate metadata fields on `file` in-place and return it.
    Never raises — on failure the fields remain None and a warning is logged.
    """
    try:
        if file.media_type in (MediaType.PHOTO, MediaType.RAW):
            _extract_exif(file)
        elif file.media_type == MediaType.VIDEO:
            _extract_video(file)
    except Exception as exc:
        logger.warning("Metadata extraction failed for %s: %s", file.path, exc)
    return file


_EXTRACT_WORKERS = 4  # metadata reads are small and I/O-bound — overlap them


def extract_all(
    files: list[MediaFile],
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[MediaFile]:
    """
    Enrich a list of MediaFile objects in parallel. Returns the same list.

    progress_cb(done, total) is called from worker threads as files finish.
    """
    total = len(files)
    if total == 0:
        return files

    done = 0
    lock = threading.Lock()

    def _one(f: MediaFile) -> None:
        nonlocal done
        extract(f)
        if progress_cb:
            with lock:
                done += 1
                n = done
            progress_cb(n, total)

    with ThreadPoolExecutor(max_workers=_EXTRACT_WORKERS) as pool:
        list(pool.map(_one, files))
    return files


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_exif(file: MediaFile) -> None:
    """Use exifread for full RAW/JPEG support, fall back to Pillow."""
    try:
        import exifread
        _exifread(file)
        return
    except ImportError:
        pass

    try:
        from PIL import Image
        _pillow_exif(file)
    except ImportError:
        logger.warning("Neither exifread nor Pillow is installed — install with: pip install exifread Pillow")


def _exifread(file: MediaFile) -> None:
    import exifread

    with open(file.path, "rb") as fh:
        tags = exifread.process_file(fh, stop_tag="EXIF SubSecTimeOriginal", details=False)

    # Capture datetime
    for tag in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        val = tags.get(tag)
        if val:
            file.captured_at = _parse_exif_date(str(val))
            if file.captured_at:
                break

    # Camera
    make = tags.get("Image Make")
    model = tags.get("Image Model")
    if make:
        file.camera_make = str(make).strip()
    if model:
        file.camera_model = str(model).strip()

    # Dimensions
    w = tags.get("EXIF ExifImageWidth") or tags.get("Image ImageWidth")
    h = tags.get("EXIF ExifImageLength") or tags.get("Image ImageLength")
    if w:
        file.width = int(str(w))
    if h:
        file.height = int(str(h))


def _pillow_exif(file: MediaFile) -> None:
    from PIL import Image
    from PIL.ExifTags import TAGS

    with Image.open(file.path) as img:
        file.width, file.height = img.size
        raw_exif = img._getexif()  # type: ignore[attr-defined]

    if not raw_exif:
        return

    exif = {TAGS.get(k, k): v for k, v in raw_exif.items()}

    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        val = exif.get(key)
        if val:
            file.captured_at = _parse_exif_date(str(val))
            if file.captured_at:
                break

    if exif.get("Make"):
        file.camera_make = str(exif["Make"]).strip()
    if exif.get("Model"):
        file.camera_model = str(exif["Model"]).strip()


def _extract_video(file: MediaFile) -> None:
    try:
        from pymediainfo import MediaInfo
        _pymediainfo(file)
    except ImportError:
        logger.warning("pymediainfo not installed — install with: pip install pymediainfo")


def _pymediainfo(file: MediaFile) -> None:
    from pymediainfo import MediaInfo

    info = MediaInfo.parse(file.path)

    for track in info.tracks:
        if track.track_type == "General":
            # Capture date
            for attr in ("encoded_date", "tagged_date", "recorded_date"):
                raw = getattr(track, attr, None)
                if raw:
                    file.captured_at = _parse_video_date(str(raw))
                    if file.captured_at:
                        break

            # Duration
            if track.duration:
                file.duration_sec = float(track.duration) / 1000.0

        elif track.track_type == "Video":
            if track.width:
                file.width = int(track.width)
            if track.height:
                file.height = int(track.height)


def _parse_exif_date(value: str) -> datetime | None:
    for fmt in _EXIF_DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_video_date(value: str) -> datetime | None:
    # pymediainfo returns various formats:
    #   "2026-03-16 10:18:09 UTC"  (Sony MP4)
    #   "UTC 2024-03-15 10:30:00"  (some cameras)
    #   "2024-03-15T10:30:00"
    value = value.replace("UTC", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
