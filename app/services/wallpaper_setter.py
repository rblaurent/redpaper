"""
Sets wallpapers per Windows 11 virtual desktop.

Strategy:
  1. Write wallpaper path to per-desktop registry key so it persists across
     reboots.
  2. Apply immediately:
       Current desktop  → IDesktopWallpaper::SetWallpaper() (COM, explicit
                          CoInitializeEx) or SystemParametersInfo fallback.
       Inactive desktop → temporarily switch with Win+Ctrl+Arrow, apply via
                          IDesktopWallpaper / SPI, then switch back.
"""
import ctypes
import ctypes.wintypes
import logging
import os
import time
import winreg

logger = logging.getLogger(__name__)

# ── Win32 constants ──────────────────────────────────────────────────────────
SPI_SETDESKWALLPAPER     = 0x0014
SPIF_UPDATEINIFILE       = 0x0001
SPIF_SENDCHANGE          = 0x0002
COINIT_APARTMENTTHREADED = 2

user32 = ctypes.windll.user32
ole32  = ctypes.windll.ole32

VDESKTOP_DESKTOPS = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer"
    r"\VirtualDesktops\Desktops"
)

# ── Keyboard input (for desktop switching) ───────────────────────────────────
VK_LWIN        = 0x5B
VK_CONTROL     = 0x11
VK_RIGHT       = 0x27
VK_LEFT        = 0x25
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD  = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.wintypes.WORD),
        ("wScan",       ctypes.wintypes.WORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 28)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT_UNION)]


# ── IDesktopWallpaper COM ─────────────────────────────────────────────────────
COM_AVAILABLE = False
try:
    import comtypes
    import comtypes.client

    CLSID_DesktopWallpaper = comtypes.GUID("{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}")
    IID_IDesktopWallpaper  = comtypes.GUID("{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}")

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left",   ctypes.c_long),
            ("top",    ctypes.c_long),
            ("right",  ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class IDesktopWallpaper(comtypes.IUnknown):
        _case_insensitive_ = True
        _iid_ = IID_IDesktopWallpaper
        _methods_ = [
            comtypes.COMMETHOD([], comtypes.HRESULT, "SetWallpaper",
                               (["in"], ctypes.c_wchar_p, "monitorID"),
                               (["in"], ctypes.c_wchar_p, "wallpaper")),
            comtypes.COMMETHOD([], comtypes.HRESULT, "GetWallpaper",
                               (["in"],  ctypes.c_wchar_p, "monitorID"),
                               (["out"], ctypes.POINTER(ctypes.c_wchar_p), "wallpaper")),
            # vtable order must match IDesktopWallpaper IDL exactly:
            comtypes.COMMETHOD([], comtypes.HRESULT, "GetMonitorDevicePathAt",
                               (["in"],  ctypes.c_uint,                    "monitorIndex"),
                               (["out"], ctypes.POINTER(ctypes.c_wchar_p), "monitorID")),
            comtypes.COMMETHOD([], comtypes.HRESULT, "GetMonitorDevicePathCount",
                               (["out"], ctypes.POINTER(ctypes.c_uint), "count")),
            comtypes.COMMETHOD([], comtypes.HRESULT, "GetMonitorRECT",
                               (["in"],  ctypes.c_wchar_p,              "monitorID"),
                               (["out"], ctypes.POINTER(RECT),          "displayRect")),
        ]

    COM_AVAILABLE = True
except Exception:
    logger.warning("comtypes not available — falling back to SPI wallpaper setter")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_registry(guid: str, abs_path: str) -> bool:
    """Write the wallpaper path to the per-desktop registry key."""
    key_path = VDESKTOP_DESKTOPS + "\\" + "{" + guid.upper() + "}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                            access=winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Wallpaper", 0, winreg.REG_SZ, abs_path)
        logger.debug("Wrote registry wallpaper for %s → %s", guid, abs_path)
        return True
    except OSError as e:
        logger.warning("Registry write failed for %s: %s", guid, e)
        return False


def _apply_com(abs_path: str, monitor_device_path: str | None = None) -> bool:
    """
    Apply wallpaper on the current desktop via IDesktopWallpaper COM.
    Explicitly initialises COM for the calling thread so this works on
    async worker threads that haven't called CoInitialize themselves.
    Pass monitor_device_path to target a specific monitor; None applies to all.
    """
    if not COM_AVAILABLE:
        return False
    # CoInitializeEx returns S_OK (0) if we initialised, S_FALSE (1) if already
    # initialised by this thread, or an error HRESULT if it fails.
    hr_init = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    we_inited = (hr_init == 0)
    try:
        wobj = comtypes.client.CreateObject(
            CLSID_DesktopWallpaper, interface=IDesktopWallpaper
        )
        # Empty string also means "all monitors" — normalise to None
        wobj.SetWallpaper(monitor_device_path or None, abs_path)
        return True
    except Exception as e:
        logger.warning("IDesktopWallpaper.SetWallpaper failed: %s", e)
        return False
    finally:
        if we_inited:
            ole32.CoUninitialize()


def _apply_spi(abs_path: str) -> bool:
    """Apply wallpaper globally via SystemParametersInfo."""
    result = user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, abs_path,
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )
    return bool(result)


def _send_vdesktop_switch(direction_key: int) -> None:
    """Send a single Win+Ctrl+Left or Win+Ctrl+Right key chord."""
    seq = [
        (VK_LWIN,      0),
        (VK_CONTROL,   0),
        (direction_key, 0),
        (direction_key, KEYEVENTF_KEYUP),
        (VK_CONTROL,   KEYEVENTF_KEYUP),
        (VK_LWIN,      KEYEVENTF_KEYUP),
    ]
    inputs = (_INPUT * len(seq))()
    for i, (vk, flags) in enumerate(seq):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i]._input.ki.wVk = vk
        inputs[i]._input.ki.dwFlags = flags
    user32.SendInput(len(seq), inputs, ctypes.sizeof(_INPUT))


def _switch_to_desktop(target_idx: int, from_idx: int) -> None:
    """Switch to a virtual desktop by index using keyboard shortcuts."""
    if target_idx == from_idx:
        return
    steps   = abs(target_idx - from_idx)
    dir_key = VK_RIGHT if target_idx > from_idx else VK_LEFT
    for step in range(steps):
        _send_vdesktop_switch(dir_key)
        # Wait between steps so DWM registers each switch
        if step < steps - 1:
            time.sleep(0.35)


# ── Public API ───────────────────────────────────────────────────────────────

def set_wallpaper_for_desktop(
    desktop_guid: str,
    image_path: str,
    desktop_index: int | None = None,
    current_index: int | None = None,
) -> bool:
    """
    Set the wallpaper for a specific virtual desktop identified by its GUID.

    1. Write path to per-desktop registry key (persists; Windows restores it on
       next switch to that desktop).
    2. Apply via COM immediately — only when this IS the currently active desktop.
       We never keyboard-switch to inactive desktops: that approach is unreliable
       and can corrupt wallpaper state across all desktops.
    Returns True when the registry write succeeded.
    """
    if not os.path.isfile(image_path):
        logger.error("Wallpaper file not found: %s", image_path)
        return False

    abs_path = os.path.abspath(image_path).replace("/", "\\")

    reg_ok = _write_registry(desktop_guid, abs_path)

    try:
        from app.services.desktop_detector import get_current_desktop_guid
        current_guid = get_current_desktop_guid()
        is_current = current_guid and current_guid.lower() == desktop_guid.lower()
    except Exception:
        is_current = False

    if is_current:
        if _apply_com(abs_path):
            logger.info("Applied wallpaper (COM) for current desktop %s", desktop_guid)
        elif _apply_spi(abs_path):
            logger.info("Applied wallpaper (SPI) for current desktop %s", desktop_guid)
        else:
            logger.warning("Failed to apply wallpaper for current desktop %s", desktop_guid)
    else:
        logger.info(
            "Wallpaper queued (registry) for inactive desktop %s — "
            "will be visible on next switch to that desktop", desktop_guid,
        )

    return reg_ok


def set_wallpaper_current_desktop(image_path: str) -> bool:
    """Set wallpaper on the currently active virtual desktop."""
    abs_path = os.path.abspath(image_path).replace("/", "\\")
    if _apply_com(abs_path):
        return True
    return _apply_spi(abs_path)


def set_wallpapers_for_desktop(
    desktop_guid: str,
    monitor_wallpapers: list[tuple[str | None, str]],
    # list of (monitor_device_path_or_None, image_path)
    desktop_index: int | None = None,
    current_index: int | None = None,
) -> bool:
    """
    Set wallpapers for one or more monitors on a specific virtual desktop.

    monitor_wallpapers is a list of (monitor_device_path, image_path) pairs.
    Use None as the device_path to apply to all monitors at once.

    1. Write the first entry's path to the per-desktop registry key.
    2. Apply via COM immediately — only when this IS the currently active desktop.
       We never keyboard-switch to inactive desktops: that approach is unreliable
       and corrupts wallpaper state across desktops.
    Returns True when the registry write succeeded.
    """
    if not monitor_wallpapers:
        return False

    abs_pairs: list[tuple[str | None, str]] = []
    for device_path, image_path in monitor_wallpapers:
        if not os.path.isfile(image_path):
            logger.error("Wallpaper file not found: %s", image_path)
            return False
        abs_path = os.path.abspath(image_path).replace("/", "\\")
        abs_pairs.append((device_path or None, abs_path))

    # Registry only stores one path per virtual desktop — use the first one
    reg_ok = _write_registry(desktop_guid, abs_pairs[0][1])

    try:
        from app.services.desktop_detector import get_current_desktop_guid
        current_guid = get_current_desktop_guid()
        is_current = current_guid and current_guid.lower() == desktop_guid.lower()
    except Exception:
        is_current = False

    if is_current:
        for device_path, abs_path in abs_pairs:
            if not _apply_com(abs_path, device_path):
                _apply_spi(abs_path)
        logger.info("Applied wallpapers (multi-monitor) for current desktop %s", desktop_guid)
    else:
        logger.info(
            "Wallpapers queued (registry) for inactive desktop %s — "
            "will be visible on next switch to that desktop", desktop_guid,
        )

    return reg_ok
