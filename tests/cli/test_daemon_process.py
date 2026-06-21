from __future__ import annotations

import os
from pathlib import Path

import pytest

from cogito_agent.cli.daemon import _default_pid_path
from cogito_agent.cli.process import AlreadyRunningError, PidFile


def test_pid_file_acquire_and_release(tmp_path: Path) -> None:
    target = tmp_path / "cogito.pid"

    with PidFile(target):
        assert target.read_text(encoding="ascii").strip() == str(os.getpid())

    assert not target.exists()


def test_pid_file_rejects_live_owner(tmp_path: Path) -> None:
    target = tmp_path / "cogito.pid"
    target.write_text(str(os.getpid()), encoding="ascii")

    with pytest.raises(AlreadyRunningError, match="already running"):
        PidFile(target).acquire()


def test_pid_file_replaces_stale_or_invalid_owner(tmp_path: Path) -> None:
    target = tmp_path / "cogito.pid"
    target.write_text("not-a-pid", encoding="ascii")

    guard = PidFile(target)
    guard.acquire()
    try:
        assert target.read_text(encoding="ascii").strip() == str(os.getpid())
    finally:
        guard.release()


def test_default_pid_path_is_next_to_database(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "cogito.db"
    assert _default_pid_path(str(db_path)) == str(db_path.resolve().with_name("cogito.pid"))
