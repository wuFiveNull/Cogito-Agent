"""Tests for SecretProvider implementations."""
from __future__ import annotations

import gc
import os
import tempfile

from cogito_agent.security import (
    EnvSecretProvider,
    LocalSecretsProvider,
    SecretValue,
)


def test_secret_value_hides_value():
    sv = SecretValue("my-secret-value", name="test_key")
    assert "[REDACTED]" in repr(sv)
    assert "[REDACTED]" in str(sv)
    assert sv.value == "my-secret-value"


def test_secret_value_str_not_equal_value():
    sv = SecretValue("my-secret-value")
    assert str(sv) != "my-secret-value"


def test_secret_value_len():
    sv = SecretValue("12345")
    assert len(sv) == 5


def test_secret_value_bool():
    assert bool(SecretValue("x")) is True
    assert bool(SecretValue("")) is False


def test_secret_value_eq():
    a = SecretValue("hello")
    b = SecretValue("hello")
    c = SecretValue("world")
    assert a == b
    assert a != c


def test_env_provider_set_and_get():
    provider = EnvSecretProvider(prefix="COGITO_TEST_")
    provider.set_secret("MY_KEY", "my_value")
    sv = provider.get_secret("MY_KEY")
    assert sv is not None
    assert sv.value == "my_value"
    assert str(sv) != "my_value"
    provider.delete_secret("MY_KEY")


def test_env_provider_list():
    provider = EnvSecretProvider(prefix="COGITO_TEST_")
    os.environ["COGITO_TEST_KEY_A"] = "v1"
    os.environ["COGITO_TEST_KEY_B"] = "v2"
    keys = provider.list_keys()
    assert "KEY_A" in keys
    assert "KEY_B" in keys
    del os.environ["COGITO_TEST_KEY_A"]
    del os.environ["COGITO_TEST_KEY_B"]


def test_env_provider_delete():
    provider = EnvSecretProvider(prefix="COGITO_TEST_")
    os.environ["COGITO_TEST_DELETEME"] = "val"
    assert provider.delete_secret("DELETEME") is True
    assert provider.delete_secret("NONEXISTENT") is False
    assert provider.get_secret("DELETEME") is None


def test_env_provider_rotate():
    provider = EnvSecretProvider(prefix="COGITO_TEST_")
    os.environ["COGITO_TEST_ROTATEME"] = "old"
    provider.rotate_secret("ROTATEME", "new")
    sv = provider.get_secret("ROTATEME")
    assert sv is not None
    assert sv.value == "new"
    del os.environ["COGITO_TEST_ROTATEME"]


def _cleanup_db(path: str) -> None:
    gc.collect()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


def test_local_provider_set_and_get():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        provider.set_secret("my_key", "my_value")
        sv = provider.get_secret("my_key")
        assert sv is not None
        assert sv.value == "my_value"
        assert str(sv) != "my_value"
    finally:
        _cleanup_db(db_path)


def test_local_provider_list():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        provider.set_secret("k1", "v1")
        provider.set_secret("k2", "v2")
        keys = provider.list_keys()
        assert "k1" in keys
        assert "k2" in keys
    finally:
        _cleanup_db(db_path)


def test_local_provider_delete():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        provider.set_secret("del_me", "val")
        assert provider.delete_secret("del_me") is True
        assert provider.delete_secret("nonexistent") is False
    finally:
        _cleanup_db(db_path)


def test_local_provider_rotate():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        provider.set_secret("rot", "old")
        assert provider.rotate_secret("rot", "new") is True
        sv = provider.get_secret("rot")
        assert sv is not None
        assert sv.value == "new"
    finally:
        _cleanup_db(db_path)


def test_local_provider_metadata():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        provider.set_secret("meta_key", "val")
        m = provider.metadata("meta_key")
        assert m is not None
        assert m["key"] == "meta_key"
        assert m["created_at"] is not None
        assert m["updated_at"] is not None
        assert m["last_used_at"] is None
        provider.get_secret("meta_key")
        m2 = provider.metadata("meta_key")
        assert m2 is not None
        assert m2["last_used_at"] is not None
    finally:
        _cleanup_db(db_path)


def test_local_provider_all_metadata():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        provider.set_secret("a", "1")
        provider.set_secret("b", "2")
        all_m = provider.all_metadata()
        assert len(all_m) == 2
        keys = [m["key"] for m in all_m]
        assert "a" in keys
        assert "b" in keys
    finally:
        _cleanup_db(db_path)


def test_local_provider_nonexistent():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        provider = LocalSecretsProvider(db_path)
        assert provider.get_secret("nonexistent") is None
    finally:
        _cleanup_db(db_path)
