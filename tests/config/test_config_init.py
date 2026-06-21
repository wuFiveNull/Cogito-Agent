from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cogito_agent.cli import run_cli
from cogito_agent.config import initialize_config, load_config


def test_initialize_config_creates_valid_toml(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    result = initialize_config(str(target))

    assert result == str(target)
    assert target.is_file()
    config = load_config(config_path=str(target))
    assert config.model.provider == "mock"
    assert config.storage.db_path == "~/.cogito/cogito.db"
    assert config.security.cors_origins == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def test_initialize_config_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text('[model]\nprovider = "ollama"\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        initialize_config(str(target))

    assert "ollama" in target.read_text(encoding="utf-8")


def test_initialize_config_force_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    target.write_text("invalid", encoding="utf-8")

    initialize_config(str(target), force=True)

    assert load_config(config_path=str(target)).model.provider == "mock"


def test_cli_config_init_creates_requested_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "custom.toml"
    monkeypatch.setattr(
        sys,
        "argv",
        ["cogito", "config", "init", "--path", str(target)],
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    run_cli()

    assert target.is_file()
    assert f"Created configuration: {target}" in capsys.readouterr().out
