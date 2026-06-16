from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from cogito_agent.cli.config_manager import (
    CONFIG_DIR,
    CONFIG_PATH,
    KEYS,
    DEFAULT_CONFIG,
    get_config,
    get_config_key,
    set_config_key,
    doctor,
)


def _isolate_config(monkeypatch: object) -> str:
    tmp = tempfile.mkdtemp()
    if isinstance(monkeypatch, type(None)):
        import pytest
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr("cogito_agent.cli.config_manager.CONFIG_DIR", tmp)
        monkeypatch.setattr("cogito_agent.cli.config_manager.CONFIG_PATH", os.path.join(tmp, "config.json"))
        return tmp
    monkeypatch.setattr("cogito_agent.cli.config_manager.CONFIG_DIR", tmp)
    monkeypatch.setattr("cogito_agent.cli.config_manager.CONFIG_PATH", os.path.join(tmp, "config.json"))
    return tmp


def test_get_config_defaults(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    cfg = get_config()
    assert cfg["model.provider"] == "mock"
    assert cfg["model.base_url"] == ""
    assert cfg["model.model"] == ""
    assert cfg["model.api_key_env"] == "MODEL_API_KEY"


def test_set_and_get_config_key(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "openai")
    assert get_config_key("model.provider") == "openai"
    cfg = get_config()
    assert cfg["model.provider"] == "openai"


def test_set_unknown_key_raises(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    import pytest
    with pytest.raises(ValueError, match="Unknown config key"):
        set_config_key("model.nonexistent", "value")


def test_set_all_keys(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "ollama")
    set_config_key("model.base_url", "http://localhost:11434/v1")
    set_config_key("model.model", "llama3.2")
    set_config_key("model.api_key_env", "OLLAMA_API_KEY")
    cfg = get_config()
    assert cfg["model.provider"] == "ollama"
    assert cfg["model.base_url"] == "http://localhost:11434/v1"
    assert cfg["model.model"] == "llama3.2"
    assert cfg["model.api_key_env"] == "OLLAMA_API_KEY"


def test_config_file_persistence(monkeypatch) -> None:
    tmp = _isolate_config(monkeypatch)
    cfg_path = os.path.join(tmp, "config.json")
    set_config_key("model.provider", "openai")
    assert os.path.isfile(cfg_path)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["model.provider"] == "openai"


def test_doctor_mock_provider(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "mock")
    results = doctor()
    checks = {c["check"]: c for c in results}
    assert checks["provider"]["status"] == "ok"
    assert "no API needed" in checks["provider"]["detail"]


def test_doctor_openai_provider_missing_key(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "openai")
    with patch.dict(os.environ, {}, clear=True):
        results = doctor()
    checks = {c["check"]: c for c in results}
    assert checks["provider"]["status"] == "ok"
    assert checks["api_key_env"]["status"] == "warn"


def test_doctor_openai_provider_with_key(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "openai")
    with patch.dict(os.environ, {"MODEL_API_KEY": "sk-test123"}, clear=True):
        results = doctor()
    checks = {c["check"]: c for c in results}
    assert checks["api_key_env"]["status"] == "ok"
    assert "is set" in checks["api_key_env"]["detail"]


def test_doctor_ollama_provider(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "ollama")
    set_config_key("model.base_url", "http://localhost:11434/v1")
    results = doctor()
    checks = {c["check"]: c for c in results}
    assert checks["provider"]["status"] == "ok"
    assert checks["base_url"]["status"] == "ok"


def test_doctor_unknown_provider(monkeypatch) -> None:
    _isolate_config(monkeypatch)
    set_config_key("model.provider", "nonexistent")
    results = doctor()
    checks = {c["check"]: c for c in results}
    assert checks["provider"]["status"] == "warn"


def test_keys_are_complete() -> None:
    assert set(KEYS) == set(DEFAULT_CONFIG.keys())


def test_config_survives_corrupted_file(monkeypatch) -> None:
    tmp = _isolate_config(monkeypatch)
    cfg_path = os.path.join(tmp, "config.json")
    Path(tmp).mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write("not valid json")
    cfg = get_config()
    assert cfg["model.provider"] == "mock"
