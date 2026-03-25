"""
Scanner — walks an SD card root using camera-aware profiles and returns
a ScanResult with all media files (photos, RAW, videos).

Handles camera-specific folder structures:
  Sony   → photos in DCIM/, videos in PRIVATE/M4ROOT/CLIP/
  Canon  → everything in DCIM/
  Nikon  → everything in DCIM/
  etc.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .camera_profiles import CameraProfile, detect_profile, all_search_roots
from .models import MediaFile, MediaType, classify

logger = logging.getLogger(__name__)


class ScanResult:
    def __init__(self, files: list[MediaFile], profile: CameraProfile | None = None):
        self.files = files
        self.profile = profile  # detected camera profile

    @property
    def total(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def total_size_mb(self) -> float:
        return round(self.total_size / 1_048_576, 2)

    def by_type(self, media_type: MediaType) -> list[MediaFile]:
        return [f for f in self.files if f.media_type == media_type]

    @property
    def photos(self) -> list[MediaFile]:
        return self.by_type(MediaType.PHOTO)

    @property
    def raws(self) -> list[MediaFile]:
        return self.by_type(MediaType.RAW)

    @property
    def videos(self) -> list[MediaFile]:
        return self.by_type(MediaType.VIDEO)

    def summary(self) -> str:
        cam = f" [{self.profile.name}]" if self.profile else ""
        return (
            f"Found {self.total} files ({self.total_size_mb} MB){cam} — "
            f"{len(self.photos)} photos, {len(self.raws)} RAW, {len(self.videos)} videos"
        )


def scan_card(
    sd_root: str | Path,
    *,
    include_unknown: bool = False,
    progress_cb: Callable[[int, int, Path], None] | None = None,
) -> ScanResult:
    """
    Scan an SD card root directory using camera profile detection.

    Automatically finds all media regardless of camera brand folder structure.
    For Sony: scans both DCIM/ and PRIVATE/M4ROOT/CLIP/ for videos.

    Args:
        sd_root:         SD card mount point (e.g. /Volumes/Untitled)
        include_unknown: Include files with unrecognised extensions.
        progress_cb:     callback(scanned, total, current_path)

    Returns:
        ScanResult with detected camera profile and all media files.
    """
    sd_root = Path(sd_root)

    if not sd_root.exists():
        raise FileNotFoundError(f"SD card root not found: {sd_root}")
    if not sd_root.is_dir():
        raise NotADirectoryError(f"Not a directory: {sd_root}")

    profile = detect_profile(sd_root)
    search_roots = all_search_roots(sd_root, profile)
    logger.info("Scan started: %s  profile=%s", sd_root, profile.name)

    # Fallback: if no known folders found, scan everything
    if not search_roots:
        logger.warning("No known camera folders found, scanning entire SD root")
        search_roots = [sd_root]

    # Collect all candidate file paths across all search roots
    all_paths: list[Path] = []
    seen: set[Path] = set()
    for root in search_roots:
        for p in root.rglob("*"):
            if p.is_file() and p not in seen and not _is_system_file(p):
                all_paths.append(p)
                seen.add(p)

    files: list[MediaFile] = []

    for idx, path in enumerate(all_paths):
        if progress_cb:
            progress_cb(idx, len(all_paths), path)

        media_type = classify(path)

        if media_type == MediaType.UNKNOWN and not include_unknown:
            continue

        files.append(MediaFile(
            path=path,
            media_type=media_type,
            size=path.stat().st_size,
        ))

    if progress_cb and all_paths:
        progress_cb(len(all_paths), len(all_paths), all_paths[-1])

    logger.info(
        "Scan complete: %d files (%.1f MB) — %d photos, %d RAW, %d videos",
        len(files),
        sum(f.size for f in files) / 1_048_576,
        sum(1 for f in files if f.media_type == MediaType.PHOTO),
        sum(1 for f in files if f.media_type == MediaType.RAW),
        sum(1 for f in files if f.media_type == MediaType.VIDEO),
    )
    return ScanResult(files, profile)


def scan(
    source: str | Path,
    *,
    include_unknown: bool = False,
    progress_cb: Callable[[int, int, Path], None] | None = None,
) -> ScanResult:
    """
    Scan a specific directory (not SD card root). No profile detection.
    Use scan_card() when scanning a full SD card.
    """
    source = Path(source)

    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source}")

    all_paths = [
        p for p in source.rglob("*")
        if p.is_file() and not _is_system_file(p)
    ]

    files: list[MediaFile] = []

    for idx, path in enumerate(all_paths):
        if progress_cb:
            progress_cb(idx, len(all_paths), path)

        media_type = classify(path)

        if media_type == MediaType.UNKNOWN and not include_unknown:
            continue

        files.append(MediaFile(
            path=path,
            media_type=media_type,
            size=path.stat().st_size,
        ))

    if progress_cb and all_paths:
        progress_cb(len(all_paths), len(all_paths), all_paths[-1])

    return ScanResult(files)


def _is_system_file(path: Path) -> bool:
    """Skip hidden files, camera index files, and Sony video proxy thumbnails."""
    name = path.name
    parts = [p.upper() for p in path.parts]

    # Sony proxy/thumbnail folders under M4ROOT — never media we want
    if "M4ROOT" in parts and any(f in parts for f in ("SUB", "THMBNL")):
        return True

    # Sony video clip thumbnails: PRIVATE/M4ROOT/CLIP/*.JPG (companion to each .MP4)
    if "CLIP" in parts and "M4ROOT" in parts and path.suffix.lower() == ".jpg":
        return True

    return (
        name.startswith(".")
        or path.suffix.lower() in {".ctg", ".xml", ".sav", ".dat"}
    )
