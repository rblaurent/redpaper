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
    width: int = 1920
    height: int = 1080
    current_wallpaper: str | None = None  # Windows-reported path on the current virtual desktop


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
            # comtypes returns ["out"] params as the call's return value — don't pass them manually
            n = wobj.GetMonitorDevicePathCount()
            monitors: list[MonitorInfo] = []
            for i in range(n):
                path = wobj.GetMonitorDevicePathAt(i) or ""
                w, h = 1920, 1080
                try:
                    rect = wobj.GetMonitorRECT(path)
                    w = abs(rect.right  - rect.left) or 1920
                    h = abs(rect.bottom - rect.top)  or 1080
                except Exception:
                    pass
                current_wp = None
                try:
                    current_wp = wobj.GetWallpaper(path) or None
                except Exception:
                    pass
                monitors.append(MonitorInfo(index=i, device_path=path, width=w, height=h, current_wallpaper=current_wp))
            return monitors if monitors else [MonitorInfo(index=0, device_path="")]
        finally:
            if we_inited:
                ole32.CoUninitialize()

    except Exception as exc:
        logger.warning("Monitor detection failed: %s", exc)
        return [MonitorInfo(index=0, device_path="")]
