from __future__ import annotations

import os
import platform
import plistlib
import shlex
import sys
from pathlib import Path

SERVICE_NAME = "cogito-agent"


def service_platform(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "launchd"
    return "systemd"


def default_service_path(kind: str) -> Path:
    if kind == "systemd":
        return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"
    if kind == "launchd":
        return Path.home() / "Library" / "LaunchAgents" / "io.cogito.agent.plist"
    raise ValueError(f"No file-based service path for {kind}")


def write_systemd_unit(path: str | Path, *, python: str | None = None) -> Path:
    target = Path(path)
    executable = shlex.quote(python or sys.executable)
    content = f"""[Unit]
Description=Cogito-Agent local background daemon
After=network.target

[Service]
Type=simple
ExecStart={executable} -m cogito_agent.cli.daemon
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def write_launchd_plist(path: str | Path, *, python: str | None = None) -> Path:
    target = Path(path)
    log_dir = Path.home() / ".cogito" / "logs"
    payload = {
        "Label": "io.cogito.agent",
        "ProgramArguments": [
            python or sys.executable,
            "-m",
            "cogito_agent.cli.daemon",
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(log_dir / "daemon.stdout.log"),
        "StandardErrorPath": str(log_dir / "daemon.stderr.log"),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        plistlib.dump(payload, stream, sort_keys=True)
    return target


def install_windows_service() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows service installation is only available on Windows")
    try:
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise RuntimeError("Install the 'windows-service' extra (pywin32) first") from exc
    win32serviceutil.InstallService(
        pythonClassString="cogito_agent.cli.windows_service.CogitoWindowsService",
        serviceName="CogitoAgent",
        displayName="Cogito-Agent",
        startType=win32service.SERVICE_AUTO_START,
        description="Cogito-Agent local background daemon",
    )


def uninstall_windows_service() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows service removal is only available on Windows")
    try:
        import win32serviceutil
    except ImportError as exc:
        raise RuntimeError("Install the 'windows-service' extra (pywin32) first") from exc
    try:
        win32serviceutil.StopService("CogitoAgent")
    except Exception:
        pass
    win32serviceutil.RemoveService("CogitoAgent")


def install_service(kind: str, path: str | None = None) -> str:
    if kind == "windows":
        install_windows_service()
        return "Windows service CogitoAgent"
    target = Path(path) if path else default_service_path(kind)
    if kind == "systemd":
        return str(write_systemd_unit(target))
    if kind == "launchd":
        return str(write_launchd_plist(target))
    raise ValueError(f"Unsupported service manager: {kind}")


def uninstall_service(kind: str, path: str | None = None) -> str:
    if kind == "windows":
        uninstall_windows_service()
        return "Windows service CogitoAgent"
    target = Path(path) if path else default_service_path(kind)
    target.unlink(missing_ok=True)
    return str(target)
