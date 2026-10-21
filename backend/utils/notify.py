"""
Notify — tell the user an import finished, even if they walked away.

  macOS   → Notification Center banner (osascript) with a sound
  Windows → system "asterisk" sound
  other   → no-op

Never raises; notifications are a convenience, not part of the import.
"""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def _applescript_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str, *, success: bool = True, banner: bool = True) -> None:
    """
    Show a system notification (when banner=True) and play a sound.
    success=False uses a more noticeable alert sound.
    """
    try:
        if sys.platform == "darwin":
            sound = "Glass" if success else "Basso"
            if banner:
                script = (
                    f"display notification {_applescript_str(message)} "
                    f"with title {_applescript_str(title)} sound name {_applescript_str(sound)}"
                )
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        elif sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK if success else winsound.MB_ICONHAND)
    except Exception as e:
        logger.debug("Notification failed: %s", e)
