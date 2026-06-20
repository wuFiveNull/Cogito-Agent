from __future__ import annotations

import plistlib
from pathlib import Path

from cogito_agent.cli.service import (
    install_service,
    uninstall_service,
    write_launchd_plist,
    write_systemd_unit,
)


def test_write_systemd_user_unit(tmp_path: Path) -> None:
    target = write_systemd_unit(tmp_path / "cogito.service", python="/opt/python")
    content = target.read_text(encoding="utf-8")
    assert "ExecStart=/opt/python -m cogito_agent.cli.daemon" in content
    assert "Restart=on-failure" in content
    assert "WantedBy=default.target" in content


def test_write_launchd_agent(tmp_path: Path) -> None:
    target = write_launchd_plist(tmp_path / "cogito.plist", python="/opt/python")
    with target.open("rb") as stream:
        payload = plistlib.load(stream)
    assert payload["Label"] == "io.cogito.agent"
    assert payload["ProgramArguments"] == [
        "/opt/python",
        "-m",
        "cogito_agent.cli.daemon",
    ]
    assert payload["RunAtLoad"] is True


def test_install_and_uninstall_file_service(tmp_path: Path) -> None:
    target = tmp_path / "cogito.service"
    assert install_service("systemd", str(target)) == str(target)
    assert target.is_file()
    assert uninstall_service("systemd", str(target)) == str(target)
    assert not target.exists()
