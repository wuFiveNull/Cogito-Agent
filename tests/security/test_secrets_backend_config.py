"""Tests: secrets.backend config controls which SecretProvider is used."""
from __future__ import annotations

from cogito_agent.security import (
    EnvSecretProvider,
    KeychainSecretProvider,
    LocalSecretsProvider,
    get_provider_from_config,
)


def test_backend_local_default():
    provider = get_provider_from_config({"secrets.backend": "local"})
    assert isinstance(provider, LocalSecretsProvider)


def test_backend_env():
    provider = get_provider_from_config({"secrets.backend": "env"})
    assert isinstance(provider, EnvSecretProvider)


def test_backend_keychain():
    provider = get_provider_from_config({
        "secrets.backend": "keychain",
        "secrets.service_name": "cogito-test",
    })
    assert isinstance(provider, KeychainSecretProvider)
    # May or may not be available - that's fine
    assert hasattr(provider, "available")


def test_backend_local_with_path():
    provider = get_provider_from_config({
        "secrets.backend": "local",
        "secrets.local_path": "/tmp/test_secrets.db",
    })
    assert isinstance(provider, LocalSecretsProvider)
