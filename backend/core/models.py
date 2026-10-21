from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class MediaType(str, Enum):
    PHOTO = "photo"
    RAW = "raw"
    VIDEO = "video"
    UNKNOWN = "unknown"


# File extensions grouped by media type
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".srw"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mts", ".m2ts", ".avi", ".mkv", ".m4v", ".3gp"}


def classify(path: Path) -> MediaType:
    ext = path.suffix.lower()
    if ext in PHOTO_EXTENSIONS:
        return MediaType.PHOTO
    if ext in RAW_EXTENSIONS:
        return MediaType.RAW
    if ext in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    return MediaType.UNKNOWN


@dataclass
class MediaFile:
    path: Path
    media_type: MediaType
    size: int  # bytes

    # Populated by metadata extractor
    captured_at: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None  # video only

    # Populated by dedup
    file_hash: str | None = None

    # Populated by rule engine
    dest_path: Path | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()

    @property
    def size_bytes(self) -> int:
        return self.size

    @property
    def size_mb(self) -> float:
        return round(self.size / 1_048_576, 2)

    def __repr__(self) -> str:
        return f"MediaFile({self.name}, {self.media_type.value}, {self.size_mb}MB)"
