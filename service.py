"""
Windows Service wrapper for redpaper.
Install:  python service.py install
Start:    python service.py start   (or: net start redpaper)
Stop:     python service.py stop
Remove:   python service.py remove
"""
import json
import logging
import os
import sys
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import servicemanager
import win32event
import win32service
import win32serviceutil

logger = logging.getLogger(__name__)


class RedpaperService(win32serviceutil.ServiceFramework):
    _svc_name_ = "redpaper"
    _svc_display_name_ = "Redpaper Wallpaper Service"
    _svc_description_ = "Generates AI wallpapers daily and serves the redpaper web UI."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._server_thread: threading.Thread | None = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)
        self._shutdown_server()

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._start_server()
        # Wait until stop signal
        win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)

    def _start_server(self):
        self._server_thread = threading.Thread(target=self._run_uvicorn, daemon=True)
        self._server_thread.start()

    def _run_uvicorn(self):
        import uvicorn
        try:
            with open(os.path.join(BASE_DIR, "config.json")) as f:
                cfg = json.load(f)
            port = cfg.get("web_port", 8080)
        except Exception:
            port = 8080

        # Change working directory so relative paths work
        os.chdir(BASE_DIR)

        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=port,
            reload=False,
            log_level="info",
        )

    def _shutdown_server(self):
        # uvicorn doesn't have a clean external shutdown in this threading model;
        # the daemon thread will be killed when the service process exits.
        pass


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Called by SCM
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(RedpaperService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(RedpaperService)
