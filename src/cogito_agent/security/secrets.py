from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol


class SecretValue:
    """Wraps a secret string with safe repr/str to prevent accidental leakage.

    The raw value is accessible ONLY through .value.
    Do NOT use str() or repr() to obtain the raw secret — they always
    return ``[REDACTED]``.
    """

    def __init__(self, value: str, name: str = "") -> None:
        self._value = value
        self._name = name

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"SecretValue(name={self._name!r}, value=[REDACTED])"

    def __str__(self) -> str:
        return "[REDACTED]"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretValue):
            return self._value == other._value
        return NotImplemented

    def __len__(self) -> int:
        return len(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)


class SecretProvider(Protocol):
    """Protocol for secret providers."""

    def get_secret(self, key: str) -> SecretValue | None: ...

    def list_keys(self) -> list[str]: ...

    def set_secret(self, key: str, value: str) -> None: ...

    def delete_secret(self, key: str) -> bool: ...

    def rotate_secret(self, key: str, new_value: str) -> bool: ...


class EnvSecretProvider:
    """Reads secrets from environment variables with a prefix."""

    def __init__(self, prefix: str = "COGITO_") -> None:
        self._prefix = prefix.upper()

    def _env_key(self, key: str) -> str:
        return f"{self._prefix}{key.upper()}"

    def get_secret(self, key: str) -> SecretValue | None:
        val = os.environ.get(self._env_key(key))
        if val is None:
            return None
        return SecretValue(val, name=key)

    def list_keys(self) -> list[str]:
        return [k[len(self._prefix):] for k in os.environ
                if k.startswith(self._prefix)]

    def set_secret(self, key: str, value: str) -> None:
        os.environ[self._env_key(key)] = value

    def delete_secret(self, key: str) -> bool:
        env_key = self._env_key(key)
        if env_key in os.environ:
            del os.environ[env_key]
            return True
        return False

    def rotate_secret(self, key: str, new_value: str) -> bool:
        self.set_secret(key, new_value)
        return True

    def __repr__(self) -> str:
        return f"EnvSecretProvider(prefix={self._prefix!r})"


class LocalSecretsProvider:
    """Stores secrets in a local SQLite database.

    IMPORTANT: This provider does NOT encrypt secrets at rest.
    The SQLite database file stores values as plaintext base64.
    Do NOT use for production-grade security requirements.
    For real encryption, use OS keychain (KeychainSecretProvider placeholder).
    """

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            from pathlib import Path
            db_path = str(Path.home() / ".cogito" / "secrets.db")
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        import sqlite3
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS secrets ("
                "  key TEXT PRIMARY KEY,"
                "  value TEXT NOT NULL,"
                "  created_at TEXT NOT NULL,"
                "  updated_at TEXT NOT NULL,"
                "  last_used_at TEXT"
                ")"
            )
            conn.commit()

    def get_secret(self, key: str) -> SecretValue | None:
        import sqlite3
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM secrets WHERE key = ?", (key,)
                ).fetchone()
                if row is None:
                    return None
                # Update last_used_at
                conn.execute(
                    "UPDATE secrets SET last_used_at = ? WHERE key = ?",
                    (datetime.now(UTC).isoformat(), key),
                )
                conn.commit()
                return SecretValue(row[0], name=key)
        except sqlite3.OperationalError:
            return None

    def list_keys(self) -> list[str]:
        import sqlite3
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT key FROM secrets ORDER BY key"
                ).fetchall()
                return [r[0] for r in rows]
        except sqlite3.OperationalError:
            return []

    def set_secret(self, key: str, value: str) -> None:
        import sqlite3
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            existing = conn.execute(
                "SELECT 1 FROM secrets WHERE key = ?", (key,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE secrets SET value = ?, updated_at = ? WHERE key = ?",
                    (value, now, key),
                )
            else:
                conn.execute(
                    "INSERT INTO secrets (key, value, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (key, value, now, now),
                )
            conn.commit()

    def delete_secret(self, key: str) -> bool:
        import sqlite3
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM secrets WHERE key = ?", (key,)
            )
            conn.commit()
            return cur.rowcount > 0

    def rotate_secret(self, key: str, new_value: str) -> bool:
        import sqlite3
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE secrets SET value = ?, updated_at = ? WHERE key = ?",
                (new_value, now, key),
            )
            conn.commit()
            return cur.rowcount > 0

    def metadata(self, key: str) -> dict[str, Any] | None:
        import sqlite3
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT key, created_at, updated_at, last_used_at"
                    " FROM secrets WHERE key = ?", (key,)
                ).fetchone()
                if row is None:
                    return None
                return {
                    "key": row[0],
                    "created_at": row[1],
                    "updated_at": row[2],
                    "last_used_at": row[3],
                }
        except sqlite3.OperationalError:
            return None

    def all_metadata(self) -> list[dict[str, Any]]:
        import sqlite3
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT key, created_at, updated_at, last_used_at"
                    " FROM secrets ORDER BY key"
                ).fetchall()
                return [
                    {
                        "key": r[0],
                        "created_at": r[1],
                        "updated_at": r[2],
                        "last_used_at": r[3],
                    }
                    for r in rows
                ]
        except sqlite3.OperationalError:
            return []

    def __repr__(self) -> str:
        return f"LocalSecretsProvider(db_path={self._db_path!r})"


def _keyring_available() -> bool:
    """Check if the keyring library is available and usable."""
    try:
        import keyring
        # Attempt a simple get to verify the backend works
        keyring.get_keyring()
        return True
    except Exception:
        return False


def _platform_keychain_available() -> bool:
    """Check if a platform-specific keychain tool is available."""
    import platform
    import subprocess
    system = platform.system()
    try:
        if system == "Windows":
            return bool(os.environ.get("USERNAME"))
        elif system == "Darwin":
            subprocess.run(["security", "help"], capture_output=True, timeout=2)
            return True
        elif system == "Linux":
            subprocess.run(["secret-tool", "--help"], capture_output=True, timeout=2)
            return True
    except Exception:
        pass
    return False


class KeychainSecretProvider:
    """OS keychain-backed secret provider.

    Uses the ``keyring`` library if available, with platform-specific fallbacks:
    - Windows: Credential Manager
    - macOS: Keychain
    - Linux: libsecret / GNOME Keyring / Secret Service

    If no keychain backend is available, operations raise ``ProviderError``
    with code ``SECRET_MISSING`` and a clear message.
    """

    def __init__(self, service_name: str = "cogito-agent") -> None:
        self._service_name = service_name
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        if _keyring_available():
            return "keyring"
        if _platform_keychain_available():
            import platform
            return f"platform:{platform.system().lower()}"
        return "unavailable"

    @property
    def available(self) -> bool:
        return self._backend != "unavailable"

    def _require_backend(self) -> None:
        if not self.available:
            from cogito_agent.models.provider_errors import (
                ProviderError,
                ProviderErrorCode,
            )
            raise ProviderError(
                ProviderErrorCode.SECRET_MISSING,
                "No OS keychain backend available. "
                "Install keyring: pip install keyring, "
                "or use LocalSecretsProvider / EnvSecretProvider.",
            )

    def get_secret(self, key: str) -> SecretValue | None:
        self._require_backend()
        try:
            if self._backend == "keyring":
                import keyring
                val = keyring.get_password(self._service_name, key)
                if val is None:
                    return None
                return SecretValue(val, name=key)
            return self._platform_get(key)
        except Exception:
            return None

    def _platform_get(self, key: str) -> SecretValue | None:
        import platform
        import subprocess
        system = platform.system()
        try:
            if system == "Windows":
                return self._win_get(key)
            elif system == "Darwin":
                result = subprocess.run(
                    ["security", "find-generic-password",
                     "-s", self._service_name, "-a", key, "-w"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return SecretValue(result.stdout.strip(), name=key)
                return None
            elif system == "Linux":
                result = subprocess.run(
                    ["secret-tool", "lookup",
                     "service", self._service_name, "key", key],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return SecretValue(result.stdout.strip(), name=key)
                return None
        except Exception:
            return None
        return None

    def _win_get(self, key: str) -> SecretValue | None:
        import subprocess
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-StoredCredential -Target '{self._service_name}:{key}').Password"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return SecretValue(result.stdout.strip(), name=key)
        except Exception:
            pass
        return None

    def list_keys(self) -> list[str]:
        self._require_backend()
        try:
            if self._backend == "keyring":
                # keyring doesn't natively support listing keys
                # Return empty - users should know their keys
                return []
            return self._platform_list_keys()
        except Exception:
            return []

    def _platform_list_keys(self) -> list[str]:
        import platform
        import subprocess
        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["security", "dump-keychain", "-r"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    keys = []
                    for line in result.stdout.splitlines():
                        if f'"svce"<blob>="{self._service_name}.' in line:
                            key = line.split('=')[1].strip().strip('"')
                            key = key.replace(f"{self._service_name}.", "")
                            keys.append(key)
                    return keys
                return []
            elif system == "Linux":
                # secret-tool doesn't support listing easily
                return []
        except Exception:
            return []
        return []

    def set_secret(self, key: str, value: str) -> None:
        self._require_backend()
        try:
            if self._backend == "keyring":
                import keyring
                keyring.set_password(self._service_name, key, value)
                return
            self._platform_set(key, value)
        except Exception as exc:
            from cogito_agent.models.provider_errors import (
                ProviderError,
                ProviderErrorCode,
            )
            raise ProviderError(
                ProviderErrorCode.UNKNOWN_ERROR,
                f"Failed to store secret in keychain: {exc}",
            ) from exc

    def _platform_set(self, key: str, value: str) -> None:
        import platform
        import subprocess
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(
                    ["security", "add-generic-password",
                     "-s", self._service_name, "-a", key, "-w", value, "-U"],
                    capture_output=True, timeout=5, check=True,
                )
            elif system == "Linux":
                subprocess.run(
                    ["secret-tool", "store",
                     "service", self._service_name, "key", key],
                    input=value.encode(), capture_output=True, timeout=5, check=True,
                )
            elif system == "Windows":
                subprocess.run(
                    ["powershell", "-Command",
                     f"$c=New-Object PSCredential '{self._service_name}:{key}',"
                     f"(ConvertTo-SecureString '{value}' -AsPlainText -Force);"
                     f"$c | Microsoft.PowerShell.SecretManagement.Set-Secret"],
                    capture_output=True, timeout=5, check=True,
                )
        except Exception as exc:
            from cogito_agent.models.provider_errors import (
                ProviderError,
                ProviderErrorCode,
            )
            raise ProviderError(
                ProviderErrorCode.UNKNOWN_ERROR,
                f"OS keychain set failed: {exc}",
            ) from exc

    def delete_secret(self, key: str) -> bool:
        self._require_backend()
        try:
            if self._backend == "keyring":
                import keyring
                try:
                    keyring.delete_password(self._service_name, key)
                    return True
                except keyring.errors.PasswordDeleteError:
                    return False
            return self._platform_delete(key)
        except Exception:
            return False

    def _platform_delete(self, key: str) -> bool:
        import platform
        import subprocess
        system = platform.system()
        try:
            if system == "Darwin":
                result = subprocess.run(
                    ["security", "delete-generic-password",
                     "-s", self._service_name, "-a", key],
                    capture_output=True, timeout=5,
                )
                return result.returncode == 0
            elif system == "Linux":
                result = subprocess.run(
                    ["secret-tool", "clear",
                     "service", self._service_name, "key", key],
                    capture_output=True, timeout=5,
                )
                return result.returncode == 0
            elif system == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command",
                     f"Microsoft.PowerShell.SecretManagement.Remove-Secret"
                     f" -Name '{self._service_name}:{key}'"],
                    capture_output=True, timeout=5,
                )
                return result.returncode == 0
        except Exception:
            pass
        return False

    def rotate_secret(self, key: str, new_value: str) -> bool:
        try:
            self.delete_secret(key)
            self.set_secret(key, new_value)
            return True
        except Exception:
            return False

    def __repr__(self) -> str:
        return f"KeychainSecretProvider(service={self._service_name!r}, backend={self._backend!r})"
