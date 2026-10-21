"""
Config — load/save user settings to ~/.media-porter/config.toml

Persists:
  - destination photo_base and video_base paths
  - last used drive UUIDs (future)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_DIR  = Path.home() / ".media-porter"
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


def get_rules() -> dict:
    """Return rule templates from config, falling back to defaults for missing keys."""
    from backend.core.rules import DEFAULT_TEMPLATES
    data = load()
    saved = data.get("rules", {})
    return {**DEFAULT_TEMPLATES, **saved}


def save_rules(rules: dict) -> None:
    """Persist rule templates to config."""
    data = load()
    data["rules"] = {k: v for k, v in rules.items() if isinstance(v, str)}
    save(data)


def get_dark_mode() -> bool:
    """Return True if dark mode is enabled."""
    return bool(load().get("ui", {}).get("dark_mode", False))


def save_dark_mode(dark: bool) -> None:
    """Persist dark mode preference."""
    data = load()
    data.setdefault("ui", {})["dark_mode"] = dark
    save(data)


THEME_MODES = ("system", "light", "dark")


def get_theme_mode() -> str:
    """
    Return "system", "light" or "dark". Configs written before the System
    option existed only have ui.dark_mode — honour that choice.
    """
    ui = load().get("ui", {})
    mode = ui.get("theme")
    if mode in THEME_MODES:
        return mode
    if "dark_mode" in ui:
        return "dark" if ui["dark_mode"] else "light"
    return "system"


def save_theme_mode(mode: str) -> None:
    if mode not in THEME_MODES:
        raise ValueError(f"Unknown theme mode: {mode!r}")
    data = load()
    data.setdefault("ui", {})["theme"] = mode
    save(data)


def get_auto_scan() -> bool:
    """Return True if a newly inserted camera card should be scanned automatically."""
    return bool(load().get("ui", {}).get("auto_scan", True))


def save_auto_scan(enabled: bool) -> None:
    data = load()
    data.setdefault("ui", {})["auto_scan"] = enabled
    save(data)


def get_window_state() -> dict:
    """Saved window layout: geometry, sidebar widths/visibility, file view mode."""
    state = load().get("window", {})
    return state if isinstance(state, dict) else {}


def save_window_state(state: dict) -> None:
    data = load()
    data["window"] = state
    save(data)
