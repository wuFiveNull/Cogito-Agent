from __future__ import annotations

from .secrets import (
    DevSqliteSecretProvider,
    EnvSecretProvider,
    KeychainSecretProvider,
    LocalEncryptedSecretProvider,
    LocalSecretsProvider,
    SecretProvider,
    SecretValue,
)


def get_provider_from_config(config: dict[str, str] | None = None) -> SecretProvider:
    """Create a SecretProvider based on config.

    Reads ``secrets.backend`` (env | local | dev_sqlite | local_encrypted | keychain)
    and returns the corresponding provider.

    Falls back to ``DevSqliteSecretProvider``.
    """
    if config is None:
        from cogito_agent.cli.config_manager import get_config

        config = get_config()
    backend = config.get("secrets.backend", "dev_sqlite")
    service_name = config.get("secrets.service_name", "cogito-agent")
    local_path = config.get("secrets.local_path", "")

    if backend == "env":
        return EnvSecretProvider()
    if backend == "keychain":
        return KeychainSecretProvider(service_name=service_name)
    if backend == "local_encrypted":
        return LocalEncryptedSecretProvider()
    if backend == "local":
        if local_path:
            return LocalSecretsProvider(db_path=local_path)
        return LocalSecretsProvider()
    # Default: dev_sqlite
    if local_path:
        return DevSqliteSecretProvider(db_path=local_path)
    return DevSqliteSecretProvider()


__all__ = [
    "SecretProvider",
    "SecretValue",
    "EnvSecretProvider",
    "LocalSecretsProvider",
    "LocalEncryptedSecretProvider",
    "KeychainSecretProvider",
    "DevSqliteSecretProvider",
    "get_provider_from_config",
]
