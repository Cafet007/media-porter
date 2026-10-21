"""
Messages — turn low-level error strings into sentences a photographer can act on.
"""

from __future__ import annotations

# (substring to look for, lowercase) → plain-language explanation
_ERROR_HINTS: list[tuple[str, str]] = [
    ("destination exists",  "A different file with this name is already at the destination."),
    ("not enough space",    "The destination drive is full."),
    ("no space left",       "The destination drive is full."),
    ("write blocked",       "Blocked: the destination is on the camera card."),
    ("source == destination", "Source and destination are the same file."),
    ("no such file",        "The file disappeared — was the card removed?"),
    ("permission denied",   "No permission to write to the destination folder."),
    ("read-only file system", "The destination drive is read-only."),
    ("input/output error",  "Read/write error — the card or drive may be failing."),
    ("errno 5",             "Read/write error — the card or drive may be failing."),
    ("cancelled",           "Cancelled before it was copied."),
]


def describe_error(error: str) -> str:
    """Return a plain-language explanation for an import error string."""
    lowered = error.lower()
    for needle, message in _ERROR_HINTS:
        if needle in lowered:
            return message
    return error


def format_duration(seconds: float) -> str:
    """Short human duration: '45 s', '6 min', '1 h 20 min'."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def format_size(num_bytes: float) -> str:
    """'812 MB' below 1 GB, otherwise '38.2 GB'."""
    if num_bytes < 1_073_741_824:
        return f"{num_bytes / 1_048_576:.0f} MB"
    return f"{num_bytes / 1_073_741_824:.1f} GB"
