"""
Drive Detector — finds only external storage devices (SD cards, USB drives,
external SSDs/HDDs). Internal drives are always excluded.

Detection strategy:
  Mac     → diskutil info: filter by Ejectable=True or protocol not in internal set
  Windows → GetDriveTypeW: only Removable (2) and Fixed external (3 on USB)
  Linux   → only /media and /mnt mounts (system never mounts internal there)
"""

from __future__ import annotations

import logging
import platform
import string
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

OS = platform.system()  # "Darwin" | "Windows" | "Linux"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DriveInfo:
    mount_point: Path
    label: str
    protocol: str           # "SD", "USB", "Thunderbolt", "SATA", "Internal", "Unknown"
    filesystem: str         # "ExFAT", "FAT32", "APFS", "HFS+", "NTFS", ...
    total_bytes: int        # total capacity
    free_bytes: int
    is_removable: bool
    has_dcim: bool

    # Unique identifiers
    volume_uuid: str | None = None   # changes only if reformatted  e.g. "A1B2C3D4-E5F6-..."
    disk_uuid: str | None = None     # partition-level UUID
    serial_number: str | None = None # physical device serial (burned in at manufacturing)

    @property
    def unique_id(self) -> str:
        """Best available stable identifier for this drive."""
        return self.volume_uuid or self.disk_uuid or self.serial_number or str(self.mount_point)

    @property
    def dcim_path(self) -> Path:
        return self.mount_point / "DCIM"

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / 1_073_741_824, 1)

    @property
    def free_gb(self) -> float:
        return round(self.free_bytes / 1_073_741_824, 1)

    # Capacity threshold: drives >= 1TB are unlikely to be SD cards
    _LARGE_DRIVE_BYTES = 1_000_000_000_000  # 1 TB

    @property
    def is_camera_card(self) -> bool:
        """
        True when protocol is 'Secure Digital' (direct slot),
        OR drive has a DCIM folder (SD via USB dongle/card reader).
        """
        if self.is_internal:
            return False
        return "Secure Digital" in self.protocol or self.has_dcim

    @property
    def is_external_drive(self) -> bool:
        """
        True for USB/Thunderbolt drives that are not SD cards.
        """
        if self.is_internal or self.is_camera_card:
            return False
        return self.protocol in {
            "USB", "USB 3.0", "Thunderbolt", "FireWire",
            "IEEE 1394", "1394", "Unknown",
        }

    @property
    def is_internal(self) -> bool:
        return self.protocol in ("SATA", "NVMe", "PCIe", "Internal", "Apple Fabric")

    def __str__(self) -> str:
        kind = "SD Card" if self.is_camera_card else ("External Drive" if self.is_external_drive else "Internal")
        return f"{self.label} [{kind}] {self.total_gb}GB — {self.protocol} / {self.filesystem}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_drives() -> list[DriveInfo]:
    """Return only external storage devices — internal drives are excluded."""
    mounts = _mount_points()
    drives = []
    for mount in mounts:
        info = _inspect(mount)
        if info and not info.is_internal:
            drives.append(info)
    return drives


def find_camera_cards() -> list[DriveInfo]:
    """
    Return external drives that have a DCIM folder (camera storage).
    Automatically registers each card as a protected (read-only) path.
    """
    from backend.core.safety import protect
    cards = [d for d in list_drives() if d.has_dcim]
    for card in cards:
        protect(card.mount_point)
    return cards


def find_external_drives() -> list[DriveInfo]:
    """Return external drives without a DCIM folder (general storage)."""
    return [d for d in list_drives() if not d.has_dcim]


def eject(mount_point: Path) -> tuple[bool, str]:
    """
    Safely eject (unmount) a drive. Blocks for up to ~30 s — call it off the
    UI thread. Returns (ok, message) where message is user-presentable.
    """
    mount = str(mount_point)
    try:
        if OS == "Darwin":
            cmd = ["diskutil", "eject", mount]
        elif OS == "Windows":
            drive = mount.rstrip("\\/")
            script = (
                "(New-Object -ComObject Shell.Application).Namespace(17)"
                f".ParseName('{drive}').InvokeVerb('Eject')"
            )
            cmd = ["powershell", "-NoProfile", "-Command", script]
        else:
            cmd = ["umount", mount]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        logger.error("Eject failed for %s: %s", mount, e)
        return False, f"Could not eject: {e}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        logger.error("Eject failed for %s: %s", mount, detail)
        if "in use" in detail.lower() or "busy" in detail.lower():
            return False, "The card is still in use by another app. Close it and try again."
        return False, f"Could not eject the card. {detail}".strip()

    logger.info("Ejected %s", mount)
    return True, "Card ejected — safe to remove"


def watch(
    on_insert: Callable[[DriveInfo], None],
    on_remove: Callable[[DriveInfo], None] | None = None,
    poll_interval: float = 2.0,
) -> "DriveWatcher":
    """Watch for drive insertions/removals in a background thread."""
    watcher = DriveWatcher(on_insert, on_remove, poll_interval)
    watcher.start()
    return watcher


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

class DriveWatcher:
    def __init__(
        self,
        on_insert: Callable[[DriveInfo], None],
        on_remove: Callable[[DriveInfo], None] | None,
        poll_interval: float,
    ) -> None:
        self._on_insert = on_insert
        self._on_remove = on_remove
        self._interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._known: dict[Path, DriveInfo] = {}

    def start(self) -> None:
        for drive in list_drives():  # already filters out internal
            self._known[drive.mount_point] = drive
        self._thread = threading.Thread(target=self._loop, daemon=True, name="DriveWatcher")
        self._thread.start()
        logger.info("DriveWatcher started (poll every %.1fs)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                self._poll()
            except Exception as exc:
                logger.warning("DriveWatcher poll error: %s", exc)

    def _poll(self) -> None:
        current = {d.mount_point: d for d in list_drives()}

        for mount, drive in current.items():
            if mount not in self._known:
                logger.info("Drive inserted: %s", drive)
                self._known[mount] = drive
                try:
                    self._on_insert(drive)
                except Exception as exc:
                    logger.error("on_insert error: %s", exc)

        if self._on_remove:
            for mount, drive in list(self._known.items()):
                if mount not in current:
                    logger.info("Drive removed: %s", drive)
                    del self._known[mount]
                    try:
                        self._on_remove(drive)
                    except Exception as exc:
                        logger.error("on_remove error: %s", exc)


# ---------------------------------------------------------------------------
# Volume inspection
# ---------------------------------------------------------------------------

def _inspect(mount: Path) -> DriveInfo | None:
    try:
        stat = _disk_usage(mount)
        if stat is None:
            return None
        total, free = stat

        has_dcim = (mount / "DCIM").is_dir()
        label = mount.name

        if OS == "Darwin":
            protocol, filesystem, removable, volume_uuid, disk_uuid, serial = _mac_diskutil(mount)
        elif OS == "Windows":
            protocol, filesystem, removable, volume_uuid, disk_uuid, serial = _windows_drive_info(mount)
        else:
            protocol, filesystem, removable, volume_uuid, disk_uuid, serial = "Unknown", "Unknown", True, None, None, None

        return DriveInfo(
            mount_point=mount,
            label=label,
            protocol=protocol,
            filesystem=filesystem,
            total_bytes=total,
            free_bytes=free,
            is_removable=removable,
            has_dcim=has_dcim,
            volume_uuid=volume_uuid,
            disk_uuid=disk_uuid,
            serial_number=serial,
        )
    except Exception as exc:
        logger.debug("Could not inspect %s: %s", mount, exc)
        return None


def _disk_usage(path: Path):
    try:
        import shutil
        usage = shutil.disk_usage(path)
        return usage.total, usage.free
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Mac — diskutil info
# ---------------------------------------------------------------------------

def _mac_diskutil(mount: Path) -> tuple[str, str, bool, str | None, str | None, str | None]:
    """Run `diskutil info -plist <mount>` and extract all drive identifiers."""
    try:
        import plistlib
        result = subprocess.run(
            ["diskutil", "info", "-plist", str(mount)],
            capture_output=True, timeout=5
        )
        if result.returncode != 0:
            return "Unknown", "Unknown", True, None, None, None

        info = plistlib.loads(result.stdout)

        protocol   = info.get("BusProtocol") or info.get("Protocol") or "Unknown"
        filesystem = info.get("FilesystemName") or info.get("FilesystemType") or "Unknown"
        removable  = info.get("RemovableMedia", False) or info.get("Ejectable", False)

        # Unique identifiers
        volume_uuid = info.get("VolumeUUID")                    # changes only on reformat
        disk_uuid   = info.get("DiskUUID")                      # partition UUID
        serial      = info.get("MediaSerialNumber") or info.get("IOSerialNumber")  # physical serial

        return protocol, filesystem, bool(removable), volume_uuid, disk_uuid, serial

    except Exception as exc:
        logger.debug("diskutil failed for %s: %s", mount, exc)
        return "Unknown", "Unknown", True, None, None, None


# ---------------------------------------------------------------------------
# Windows — ctypes
# ---------------------------------------------------------------------------

def _windows_drive_info(mount: Path) -> tuple[str, str, bool, str | None, str | None, str | None]:
    try:
        import ctypes
        drive_str = str(mount)
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_str)
        bus_protocol, serial = _windows_bus_info(drive_str)
        protocol, removable = _windows_protocol_from_drive_type(drive_type, bus_protocol)

        # Volume serial number (32-bit int, not the physical serial)
        vol_serial = ctypes.c_ulong(0)
        filesystem_buf = ctypes.create_unicode_buffer(32)
        ctypes.windll.kernel32.GetVolumeInformationW(
            drive_str, None, 0, ctypes.byref(vol_serial), None, None,
            filesystem_buf, len(filesystem_buf)
        )
        volume_uuid = hex(vol_serial.value) if vol_serial.value else None
        filesystem = filesystem_buf.value or "Unknown"

        return protocol, filesystem, removable, volume_uuid, None, serial
    except Exception:
        return "Internal", "Unknown", False, None, None, None


_WINDOWS_EXTERNAL_PROTOCOLS = {
    "USB", "USB 3.0", "Thunderbolt", "FireWire", "IEEE 1394", "1394"
}


def _windows_protocol_from_drive_type(
    drive_type: int,
    bus_protocol: str | None,
) -> tuple[str, bool]:
    """Map Win32 drive type + physical bus to Media Porter's protocol model."""
    # GetDriveTypeW: 2=Removable, 3=Fixed, 4=Network, 5=CD-ROM.
    bus = (bus_protocol or "").strip() or "Unknown"
    if drive_type == 2:
        return (bus if bus != "Unknown" else "USB"), True
    if drive_type == 3:
        if bus in _WINDOWS_EXTERNAL_PROTOCOLS:
            return bus, False
        return "Internal", False
    return "Internal", False


def _windows_bus_info(drive_str: str) -> tuple[str | None, str | None]:
    """
    Return physical bus protocol and serial for a Windows drive letter.

    Many USB HDDs/SSDs report GetDriveTypeW == Fixed, so we need the physical
    disk's interface type to distinguish external storage from internal disks.
    """
    drive_id = drive_str.rstrip("\\/")
    script = (
        "$ErrorActionPreference='Stop';"
        f"$logical=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='{drive_id}'\";"
        "$partition=Get-CimAssociatedInstance -InputObject $logical "
        "-Association Win32_LogicalDiskToPartition | Select-Object -First 1;"
        "$disk=Get-CimAssociatedInstance -InputObject $partition "
        "-Association Win32_DiskDriveToDiskPartition | Select-Object -First 1;"
        "$disk | Select-Object InterfaceType,MediaType,SerialNumber | ConvertTo-Json -Compress"
    )
    try:
        import json
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None, None
        data = json.loads(result.stdout)
        protocol = data.get("InterfaceType") or data.get("MediaType")
        serial = data.get("SerialNumber")
        return _normalize_windows_protocol(protocol), serial.strip() if isinstance(serial, str) else serial
    except Exception as exc:
        logger.debug("Windows bus lookup failed for %s: %s", drive_str, exc)
        return None, None


def _normalize_windows_protocol(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    upper = text.upper()
    if upper in {"USB", "USBSTOR"}:
        return "USB"
    if "THUNDERBOLT" in upper:
        return "Thunderbolt"
    if upper in {"1394", "IEEE 1394"} or "FIREWIRE" in upper:
        return "IEEE 1394"
    if "SD" in upper or "SECURE DIGITAL" in upper:
        return "Secure Digital"
    return text


# ---------------------------------------------------------------------------
# OS mount point discovery
# ---------------------------------------------------------------------------

def _mount_points() -> list[Path]:
    if OS == "Darwin":
        return _mac_mounts()
    elif OS == "Windows":
        return _windows_mounts()
    else:
        return _linux_mounts()


_INTERNAL_PROTOCOLS = {"SATA", "NVMe", "PCIe", "Internal", "Apple Fabric", "PCI"}

def _mac_mounts() -> list[Path]:
    """
    Return only external volume mount points by pre-filtering with diskutil.
    Skips internal drives before the heavier per-volume diskutil info calls.
    """
    volumes = Path("/Volumes")
    if not volumes.exists():
        return []

    candidates = [p for p in volumes.iterdir() if p.is_dir() and not p.name.startswith(".")]

    external = []
    for mount in candidates:
        try:
            import plistlib
            result = subprocess.run(
                ["diskutil", "info", "-plist", str(mount)],
                capture_output=True, timeout=5
            )
            if result.returncode != 0:
                continue
            info = plistlib.loads(result.stdout)
            protocol = info.get("BusProtocol") or info.get("Protocol") or "Unknown"
            ejectable = info.get("Ejectable", False) or info.get("RemovableMedia", False)

            # Keep only if ejectable OR protocol is not internal
            if ejectable or protocol not in _INTERNAL_PROTOCOLS:
                external.append(mount)
        except Exception:
            continue

    return external


def _windows_mounts() -> list[Path]:
    mounts = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        if root.exists():
            mounts.append(root)
    return mounts


def _linux_mounts() -> list[Path]:
    candidates = []
    for base in (Path("/media"), Path("/mnt")):
        if base.exists():
            for p in base.rglob("*"):
                if p.is_dir() and p.parent != base:
                    candidates.append(p)
                elif p.is_dir():
                    candidates.append(p)
    return candidates
