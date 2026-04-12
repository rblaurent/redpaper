"""
Reads Windows 11 virtual desktop information from the registry.
Returns an ordered list of DesktopInfo objects (guid, name, index).
"""
import winreg
import struct
from dataclasses import dataclass, field
from typing import List


VDESKTOP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops"
DESKTOPS_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops\Desktops"


@dataclass
class DesktopInfo:
    index: int
    guid: str        # lowercase hyphenated, e.g. "3a4c1f2d-..."
    name: str = "Desktop"


def _bytes_to_guid(b: bytes) -> str:
    """Convert 16-byte little-endian GUID blob to standard string form."""
    p = struct.unpack("<IHH8B", b)
    return "{:08x}-{:04x}-{:04x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}".format(
        p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10]
    )


def get_desktops() -> List[DesktopInfo]:
    """Return ordered list of virtual desktops from registry."""
    desktops: List[DesktopInfo] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, VDESKTOP_KEY) as key:
            try:
                data, _ = winreg.QueryValueEx(key, "VirtualDesktopIDs")
            except FileNotFoundError:
                # Only one desktop exists; Windows may not write this value until a second is created
                return [DesktopInfo(index=0, guid="default", name="Desktop 1")]

        guid_bytes = bytes(data)
        count = len(guid_bytes) // 16
        guids = [_bytes_to_guid(guid_bytes[i * 16:(i + 1) * 16]) for i in range(count)]

        for idx, guid in enumerate(guids):
            name = _get_desktop_name(guid) or f"Desktop {idx + 1}"
            desktops.append(DesktopInfo(index=idx, guid=guid, name=name))

    except OSError:
        desktops = [DesktopInfo(index=0, guid="default", name="Desktop 1")]

    return desktops


def get_current_desktop_guid() -> str | None:
    """Return the GUID of the currently active virtual desktop."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, VDESKTOP_KEY) as key:
            data, _ = winreg.QueryValueEx(key, "CurrentVirtualDesktop")
            return _bytes_to_guid(bytes(data))
    except (OSError, FileNotFoundError):
        return None


def _get_desktop_name(guid: str) -> str | None:
    try:
        subkey = DESKTOPS_SUBKEY + "\\" + "{" + guid.upper() + "}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            name, _ = winreg.QueryValueEx(key, "Name")
            return name
    except (OSError, FileNotFoundError):
        return None
