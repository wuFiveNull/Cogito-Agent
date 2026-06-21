from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    """Raised when a live process already owns the daemon PID file."""


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # On Windows ``os.kill(pid, 0)`` is not a POSIX-style existence probe
        # and may terminate the target process. Query a process handle instead.
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # Access denied still means that a process owns the PID.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class PidFile:
    """Cross-platform, atomic single-process guard backed by a PID file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                owner = self._read_owner()
                if owner is not None and _process_exists(owner):
                    raise AlreadyRunningError(f"daemon already running with PID {owner}") from None
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    continue
            else:
                try:
                    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
                finally:
                    os.close(fd)
                self._owned = True
                return

    def release(self) -> None:
        if not self._owned:
            return
        try:
            owner = self._read_owner()
            if owner == os.getpid():
                self.path.unlink(missing_ok=True)
        finally:
            self._owned = False

    def _read_owner(self) -> int | None:
        try:
            return int(self.path.read_text(encoding="ascii").strip())
        except (FileNotFoundError, OSError, ValueError):
            return None

    def __enter__(self) -> PidFile:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
