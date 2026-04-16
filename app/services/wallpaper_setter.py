"""
Sets wallpapers per Windows 11 virtual desktop.

Strategy:
  1. Write wallpaper path to per-desktop registry key so it persists across
     reboots and is applied natively by Windows on next switch into that desktop.
  2. For the currently active desktop, apply immediately via
     IDesktopWallpaper::SetWallpaper (COM) per monitor, with a
     SystemParametersInfo fallback.
"""
import ctypes
import ctypes.wintypes
import logging
import os
import queue
import threading
import time
import winreg

logger = logging.getLogger(__name__)

# ── Win32 constants ──────────────────────────────────────────────────────────
SPI_SETDESKWALLPAPER     = 0x0014
SPIF_UPDATEINIFILE       = 0x0001
SPIF_SENDCHANGE          = 0x0002
COINIT_APARTMENTTHREADED = 2
CLSCTX_INPROC_SERVER     = 0x1
CLSCTX_LOCAL_SERVER      = 0x4

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


# ── Image prebake (resize to monitor dims + JPEG) ───────────────────────────

def _ensure_jpeg(image_path: str) -> str:
    """Format-only fallback: convert PNG→JPEG without resizing. Used when
    monitor dimensions are unavailable."""
    lower = image_path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return image_path

    jpg_path = os.path.splitext(image_path)[0] + ".jpg"
    if os.path.isfile(jpg_path):
        try:
            if os.path.getmtime(jpg_path) >= os.path.getmtime(image_path):
                return jpg_path
        except OSError:
            pass

    try:
        from PIL import Image
        with Image.open(image_path) as img:
            rgb = img.convert("RGB") if img.mode != "RGB" else img
            rgb.save(jpg_path, "JPEG", quality=100, subsampling=0)
        return jpg_path
    except Exception as exc:
        logger.warning("JPEG conversion failed for %s: %s — using original", image_path, exc)
        return image_path


def _prebake(image_path: str, width: int | None, height: int | None) -> str:
    """
    Resize *image_path* to exactly (width, height) and save as JPEG quality 100,
    4:4:4 chroma. When DWM receives a wallpaper that already matches the target
    monitor's pixel dimensions, it can skip its own resize/transcode pass — the
    main contributor to the on-switch UI freeze.

    Cached as ``<basename>.<W>x<H>.jpg`` next to the source. Falls back to a
    plain JPEG conversion when dimensions are missing.
    """
    if not width or not height:
        return _ensure_jpeg(image_path)

    base, _ = os.path.splitext(image_path)
    baked_path = f"{base}.{width}x{height}.jpg"

    if os.path.isfile(baked_path):
        try:
            if os.path.getmtime(baked_path) >= os.path.getmtime(image_path):
                return baked_path
        except OSError:
            pass

    try:
        from PIL import Image
        with Image.open(image_path) as img:
            rgb = img.convert("RGB") if img.mode != "RGB" else img
            if rgb.size != (width, height):
                rgb = rgb.resize((width, height), Image.Resampling.LANCZOS)
            rgb.save(baked_path, "JPEG", quality=100, subsampling=0, optimize=False)
        logger.debug("Prebaked %s → %s (%dx%d)", image_path, baked_path, width, height)
        return baked_path
    except Exception as exc:
        logger.warning("Prebake failed for %s: %s — falling back to format-only", image_path, exc)
        return _ensure_jpeg(image_path)


def ensure_jpeg_quality_setting() -> bool:
    """Disable Windows' default 85% JPEG re-compression of wallpapers by setting
    HKCU\\Control Panel\\Desktop\\JPEGImportQuality = 100. Combined with prebake,
    this makes DWM's per-monitor cache write a near no-op."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop",
                            access=winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                current, _ = winreg.QueryValueEx(k, "JPEGImportQuality")
                if current == 100:
                    return True
            except FileNotFoundError:
                pass
            winreg.SetValueEx(k, "JPEGImportQuality", 0, winreg.REG_DWORD, 100)
        logger.info("Set JPEGImportQuality=100 (skip Windows wallpaper re-compression)")
        return True
    except OSError as e:
        logger.warning("JPEGImportQuality registry write failed: %s", e)
        return False


# ── Dedicated COM worker thread ─────────────────────────────────────────────

class _ComWorker:
    """Long-lived thread that owns the COM apartment and IDesktopWallpaper object."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="com-wallpaper")
        self._thread.start()

    def _run(self):
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        wobj = self._create_com_object()
        logger.info("COM wallpaper worker thread started")

        while True:
            item = self._queue.get()
            if item is None:
                break
            abs_path, monitor_device_path, result_event, result_box = item
            try:
                if wobj is None:
                    wobj = self._create_com_object()
                wobj.SetWallpaper(monitor_device_path, abs_path)
                result_box.append(True)
            except Exception as exc:
                logger.warning("COM SetWallpaper failed: %s — recreating COM object", exc)
                wobj = self._create_com_object()
                try:
                    wobj.SetWallpaper(monitor_device_path, abs_path)
                    result_box.append(True)
                except Exception as exc2:
                    logger.warning("COM SetWallpaper retry failed: %s", exc2)
                    result_box.append(False)
            finally:
                result_event.set()

    @staticmethod
    def _create_com_object():
        # Try out-of-process first: if DesktopWallpaper is hosted in a separate
        # server, the heavy DWM transcoding happens off our process. Fall back
        # to in-proc if local-server registration isn't available.
        for clsctx in (CLSCTX_LOCAL_SERVER, CLSCTX_INPROC_SERVER):
            try:
                return comtypes.client.CreateObject(
                    CLSID_DesktopWallpaper,
                    interface=IDesktopWallpaper,
                    clsctx=clsctx,
                )
            except Exception as exc:
                logger.debug("CoCreate(clsctx=0x%x) failed: %s", clsctx, exc)
        logger.warning("Failed to create IDesktopWallpaper COM object via any CLSCTX")
        return None

    def set_wallpaper(self, abs_path: str, monitor_device_path: str | None = None) -> bool:
        """Submit a SetWallpaper call and block until the worker completes it."""
        result_event = threading.Event()
        result_box: list[bool] = []
        self._queue.put((abs_path, monitor_device_path or None, result_event, result_box))
        result_event.wait(timeout=10)
        return bool(result_box and result_box[0])


_com_worker: _ComWorker | None = None


def _get_com_worker() -> _ComWorker | None:
    global _com_worker
    if not COM_AVAILABLE:
        return None
    if _com_worker is None:
        _com_worker = _ComWorker()
    return _com_worker


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
    """Apply wallpaper via the dedicated COM worker thread."""
    worker = _get_com_worker()
    if worker is None:
        return False
    return worker.set_wallpaper(abs_path, monitor_device_path)


def _apply_spi(abs_path: str) -> bool:
    """Apply wallpaper globally via SystemParametersInfo.

    SPIF_SENDCHANGE blocks until every top-level window in the system answers
    its WM_SETTINGCHANGE — any unresponsive window stalls the call (Raymond
    Chen, devblogs/oldnewthing/20050310). Win11's own Settings app no longer
    broadcasts on wallpaper changes; we follow suit.
    """
    result = user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, abs_path,
        SPIF_UPDATEINIFILE,
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
    Set a single wallpaper for a virtual desktop (legacy single-monitor path).
    Delegates to the multi-monitor entry point with one None-keyed pair.
    """
    return set_wallpapers_for_desktop(desktop_guid, [(None, image_path)],
                                      desktop_index=desktop_index,
                                      current_index=current_index)


def set_wallpaper_current_desktop(image_path: str) -> bool:
    """Set wallpaper on the currently active virtual desktop, every monitor."""
    abs_path = os.path.abspath(image_path).replace("/", "\\")
    fast_path = _ensure_jpeg(abs_path)
    if _apply_com(fast_path):
        return True
    return _apply_spi(fast_path)


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
    A device_path of None means "apply to every detected monitor."

    Each image is **prebaked** to the exact pixel dimensions of its target
    monitor at JPEG quality 100 / 4:4:4 before being handed to DWM. Matching
    dimensions lets DWM skip its own resize/transcode pass — the dominant
    cost behind the on-switch UI freeze.

    1. Write the first prebaked path to the per-desktop registry key so Windows
       restores it natively on next switch to that desktop.
    2. When this IS the currently active desktop, apply immediately via
       IDesktopWallpaper::SetWallpaper per monitor (COM), with SPI fallback.
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

    monitors = []
    try:
        from app.services.monitor_detector import get_monitors as _get_monitors
        monitors = _get_monitors()
    except Exception as exc:
        logger.warning("Monitor enumeration failed: %s — prebake will fall back to format-only", exc)
    monitor_by_path = {m.device_path: m for m in monitors if m.device_path}

    # Per-monitor pairs prebake to that monitor's exact pixel dims.
    # None-keyed pairs ("apply to all monitors via one COM call") fall back to
    # format-only conversion since DWM will resize per monitor anyway — callers
    # that want full prebake should pass per-monitor pairs.
    prebaked: list[tuple[str | None, str]] = []
    for device_path, abs_path in abs_pairs:
        mon = monitor_by_path.get(device_path) if device_path else None
        if mon is not None:
            prebaked.append((device_path, _prebake(abs_path, mon.width, mon.height)))
        else:
            prebaked.append((device_path, _ensure_jpeg(abs_path)))

    reg_ok = _write_registry(desktop_guid, prebaked[0][1])

    try:
        from app.services.desktop_detector import get_current_desktop_guid
        current_guid = get_current_desktop_guid()
        is_current = current_guid and current_guid.lower() == desktop_guid.lower()
    except Exception:
        is_current = False

    if is_current:
        for device_path, baked_path in prebaked:
            if not _apply_com(baked_path, device_path):
                _apply_spi(baked_path)
        logger.info("Applied %d wallpaper(s) (COM) for current desktop %s",
                    len(prebaked), desktop_guid)
    else:
        logger.info(
            "Wallpapers queued (registry, %d prebaked) for inactive desktop %s — "
            "will be visible on next switch to that desktop",
            len(prebaked), desktop_guid,
        )

    return reg_ok
