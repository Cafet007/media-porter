"""
Session Report — writes a CSV file summarising a completed import.

Each row covers one file:
  filename, source_path, dest_path, size_mb, media_type, captured_at,
  status, verified

Status values: Copied, Skipped, Failed, Conflict
Verified values: Yes, No, N/A (skipped/failed files are N/A)
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from .importer import ImportResult

logger = logging.getLogger(__name__)


def write_report(result: ImportResult, dest_dir: Path, session_name: str = "") -> Path:
    """
    Write a CSV import report to dest_dir.

    Filename format:
      media-porter-report_YYYY-MM-DD_HHMMSS[_name].csv

    Returns the path to the written file.
    Raises OSError if the directory cannot be written to.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = f"_{session_name.strip()}" if session_name.strip() else ""
    filename = f"media-porter-report_{timestamp}{slug}.csv"
    report_path = dest_dir / filename

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Build a lookup: source_path → (dest_path, verified)
    copied_map: dict[str, tuple[Path, bool]] = {}
    verified_names = {f.name for f in result.verified}
    for file, dest_path in result.copied:
        copied_map[str(file.path)] = (dest_path, file.name in verified_names)

    failed_map: dict[str, str] = {str(f.path): err for f, err in result.failed}
    conflict_set = {str(f.path) for f in result.conflicts}

    rows: list[dict] = []

    for file, dest_path in result.copied:
        _, verify_ok = copied_map[str(file.path)]
        rows.append({
            "filename":     file.name,
            "source_path":  str(file.path),
            "dest_path":    str(dest_path),
            "size_mb":      f"{file.size_mb:.2f}",
            "media_type":   file.media_type.value if file.media_type else "",
            "captured_at":  file.captured_at.isoformat() if file.captured_at else "",
            "status":       "Copied",
            "verified":     "Yes" if verify_ok else "No",
        })

    for file in result.skipped:
        rows.append({
            "filename":     file.name,
            "source_path":  str(file.path),
            "dest_path":    "",
            "size_mb":      f"{file.size_mb:.2f}",
            "media_type":   file.media_type.value if file.media_type else "",
            "captured_at":  file.captured_at.isoformat() if file.captured_at else "",
            "status":       "Skipped",
            "verified":     "N/A",
        })

    for file in result.conflicts:
        rows.append({
            "filename":     file.name,
            "source_path":  str(file.path),
            "dest_path":    "",
            "size_mb":      f"{file.size_mb:.2f}",
            "media_type":   file.media_type.value if file.media_type else "",
            "captured_at":  file.captured_at.isoformat() if file.captured_at else "",
            "status":       "Conflict",
            "verified":     "N/A",
        })

    for file, err in result.failed:
        rows.append({
            "filename":     file.name,
            "source_path":  str(file.path),
            "dest_path":    "",
            "size_mb":      f"{file.size_mb:.2f}",
            "media_type":   file.media_type.value if file.media_type else "",
            "captured_at":  file.captured_at.isoformat() if file.captured_at else "",
            "status":       f"Failed: {err}",
            "verified":     "N/A",
        })

    fieldnames = [
        "filename", "source_path", "dest_path",
        "size_mb", "media_type", "captured_at",
        "status", "verified",
    ]

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total_mb = sum(file.size_mb for file, _ in result.copied)
    logger.info(
        "Report written: %s  (%d rows, %.1f MB copied)",
        report_path, len(rows), total_mb,
    )
    return report_path
