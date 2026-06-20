from __future__ import annotations

import threading

try:
    import servicemanager
    import win32service
    import win32serviceutil
except ImportError:
    servicemanager = None
    win32service = None
    win32serviceutil = None


if win32serviceutil is not None:

    class CogitoWindowsService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
        _svc_name_ = "CogitoAgent"
        _svc_display_name_ = "Cogito-Agent"
        _svc_description_ = "Cogito-Agent local background daemon"

        def __init__(self, args: list[str]) -> None:
            super().__init__(args)
            self._stop_event = threading.Event()

        def SvcStop(self) -> None:  # noqa: N802
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop_event.set()

        def SvcDoRun(self) -> None:  # noqa: N802
            from .daemon import run_daemon

            servicemanager.LogInfoMsg("Cogito-Agent service starting")
            run_daemon(stop_event=self._stop_event)
            servicemanager.LogInfoMsg("Cogito-Agent service stopped")
