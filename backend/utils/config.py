"""
Config — load/save user settings to ~/.media-mporter/config.toml

Persists:
  - destination photo_base and video_base paths
  - last used drive UUIDs (future)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR  = Path.home() / ".media-mporter"
_CONFIG_FILE = _CONFIG_DIR / "config.toml"


def _ensure_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    """Load config. Returns empty dict if file missing or unreadable."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    if not _CONFIG_FILE.exists():
        return {}

    try:
        with open(_CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.warning("Failed to load config: %s", e)
        return {}


def save(data: dict) -> None:
    """Save config dict to TOML."""
    import tomli_w
    _ensure_dir()
    try:
        with open(_CONFIG_FILE, "wb") as f:
            tomli_w.dump(data, f)
        logger.debug("Config saved to %s", _CONFIG_FILE)
    except Exception as e:
        logger.warning("Failed to save config: %s", e)


def get_dest_paths() -> tuple[str, str] | None:
    """
    Return (photo_base, video_base) strings from config, or None if not set.
    """
    data = load()
    paths = data.get("paths", {})
    photo = paths.get("photo_base", "").strip()
    video = paths.get("video_base", "").strip()
    if photo and video:
        return photo, video
    return None


def save_dest_paths(photo_base: Path | str, video_base: Path | str) -> None:
    """Persist destination paths to config."""
    data = load()
    data.setdefault("paths", {})
    data["paths"]["photo_base"] = str(photo_base)
    data["paths"]["video_base"] = str(video_base)
    save(data)
