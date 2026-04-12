"""
Enumerates physical monitors connected to the system via IDesktopWallpaper COM.
Falls back to a single anonymous monitor when COM is unavailable.
"""
import ctypes
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    index: int
    device_path: str  # e.g. "\\.\DISPLAY1\Monitor0", or "" for fallback


def get_monitors() -> list[MonitorInfo]:
    """
    Return all currently connected monitors.
    Falls back to [MonitorInfo(index=0, device_path="")] when COM is unavailable,
    preserving identical behaviour to the single-monitor legacy path.
    """
    try:
        import app.services.wallpaper_setter as ws
        if not ws.COM_AVAILABLE:
            return [MonitorInfo(index=0, device_path="")]

        import comtypes.client

        ole32 = ctypes.windll.ole32
        COINIT_APARTMENTTHREADED = 2
        hr_init = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        we_inited = (hr_init == 0)

        try:
            wobj = comtypes.client.CreateObject(
                ws.CLSID_DesktopWallpaper, interface=ws.IDesktopWallpaper
            )
            count = ctypes.c_uint(0)
            wobj.GetMonitorDevicePathCount(ctypes.byref(count))
            n = count.value
            monitors: list[MonitorInfo] = []
            for i in range(n):
                path = ctypes.c_wchar_p()
                wobj.GetMonitorDevicePathAt(i, ctypes.byref(path))
                monitors.append(MonitorInfo(index=i, device_path=path.value or ""))
            return monitors if monitors else [MonitorInfo(index=0, device_path="")]
        finally:
            if we_inited:
                ole32.CoUninitialize()

    except Exception as exc:
        logger.warning("Monitor detection failed: %s", exc)
        return [MonitorInfo(index=0, device_path="")]
