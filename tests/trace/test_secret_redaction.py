from __future__ import annotations

from typing import cast

from cogito_agent.trace import RedactionHelper
from cogito_agent.trace.redaction import (
    EnvSecretProvider,
    KeychainSecretProvider,
    SecretProvider,
)


def test_env_secret_provider_protocol_compliance() -> None:
    provider: SecretProvider = EnvSecretProvider()
    assert hasattr(provider, "get_secret")
    assert hasattr(provider, "list_keys")


def test_env_secret_provider_unknown_key() -> None:
    provider = EnvSecretProvider()
    result = provider.get_secret("DOES_NOT_EXIST_XYZ")
    assert result is None


def test_keychain_secret_provider_get_secret() -> None:
    provider = KeychainSecretProvider()
    result = provider.get_secret("any_key")
    assert result is None


def test_keychain_secret_provider_list_keys() -> None:
    provider = KeychainSecretProvider()
    result = provider.list_keys()
    assert result == []


def test_redact_dict_nested_dict() -> None:
    r = RedactionHelper()
    data = {
        "level1": {
            "level2": {
                "key": "Bearer mytoken123",
            },
        },
    }
    result = cast("dict[str, object]", r.redact_dict(data))
    assert isinstance(result, dict)
    inner = result["level1"]
    assert isinstance(inner, dict)
    inner2 = inner["level2"]
    assert isinstance(inner2, dict)
    assert "Bearer [REDACTED]" in str(inner2["key"])
    assert "mytoken123" not in str(inner2["key"])


def test_redact_dict_list_of_strings() -> None:
    r = RedactionHelper()
    data = [
        "Bearer token1",
        "no secret here",
        "Authorization: Basic abc123",
    ]
    result = cast("list[object]", r.redact_dict(data))
    assert isinstance(result, list)
    assert "Bearer [REDACTED]" in str(result[0])
    assert "token1" not in str(result[0])
    assert result[1] == "no secret here"
    assert "Authorization: [REDACTED]" in str(result[2])


def test_redact_dict_int_preserved() -> None:
    r = RedactionHelper()
    result = r.redact_dict(42)
    assert result == 42


def test_redact_dict_float_preserved() -> None:
    r = RedactionHelper()
    result = r.redact_dict(3.14)
    assert result == 3.14


def test_redact_dict_none_preserved() -> None:
    r = RedactionHelper()
    result = r.redact_dict(None)
    assert result is None


def test_redact_dict_bool_preserved() -> None:
    r = RedactionHelper()
    result = r.redact_dict(True)
    assert result is True


def test_redact_dict_preserves_non_string_values_in_dict() -> None:
    r = RedactionHelper()
    data = {
        "name": "safe name",
        "count": 100,
        "ratio": 0.5,
        "active": True,
        "metadata": None,
    }
    result = cast("dict[str, object]", r.redact_dict(data))
    assert isinstance(result, dict)
    assert result["name"] == "safe name"
    assert result["count"] == 100
    assert result["ratio"] == 0.5
    assert result["active"] is True
    assert result["metadata"] is None
