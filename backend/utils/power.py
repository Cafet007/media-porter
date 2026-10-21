"""
Power — keep the computer awake while an import is running.

An idle-sleep in the middle of a long copy stalls the import (and on some
USB enclosures drops the drive). We hold a "don't idle-sleep" assertion for
the duration of the import and release it afterwards.

  macOS   → `caffeinate -i -w <pid>` (dies with the app even if we crash)
  Windows → SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
  other   → no-op
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

_ES_CONTINUOUS      = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    """
    Usage:
        awake = KeepAwake()
        awake.start()   # idempotent
        ...
        awake.stop()    # idempotent

    On Windows the execution state is per-thread, so call start() and stop()
    from the same (UI) thread.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._active:
            return
        try:
            if sys.platform == "darwin":
                self._proc = subprocess.Popen(
                    ["caffeinate", "-i", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            elif sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(
                    _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
                )
            else:
                return
            self._active = True
            logger.info("Sleep prevention on")
        except Exception as e:
            logger.warning("Could not prevent sleep: %s", e)

    def stop(self) -> None:
        if not self._active:
            return
        try:
            if self._proc is not None:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            elif sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        except Exception as e:
            logger.warning("Could not release sleep prevention: %s", e)
        finally:
            self._proc = None
            self._active = False
            logger.info("Sleep prevention off")
