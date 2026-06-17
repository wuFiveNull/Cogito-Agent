from __future__ import annotations

from .secrets import (
    EnvSecretProvider,
    KeychainSecretProvider,
    LocalSecretsProvider,
    SecretProvider,
    SecretValue,
)


def get_provider_from_config(config: dict[str, str] | None = None) -> SecretProvider:
    """Create a SecretProvider based on config.

    Reads ``secrets.backend`` (env | local | keychain) and returns
    the corresponding provider. Falls back to ``LocalSecretsProvider``.
    """
    if config is None:
        from cogito_agent.cli.config_manager import get_config
        config = get_config()
    backend = config.get("secrets.backend", "local")
    service_name = config.get("secrets.service_name", "cogito-agent")
    local_path = config.get("secrets.local_path", "")

    if backend == "env":
        return EnvSecretProvider()
    if backend == "keychain":
        return KeychainSecretProvider(service_name=service_name)
    # Default: local
    if local_path:
        return LocalSecretsProvider(local_path)
    return LocalSecretsProvider()


__all__ = [
    "SecretProvider",
    "SecretValue",
    "EnvSecretProvider",
    "LocalSecretsProvider",
    "KeychainSecretProvider",
    "get_provider_from_config",
]
