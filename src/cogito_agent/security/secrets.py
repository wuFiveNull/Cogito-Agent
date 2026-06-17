from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol


class SecretValue:
    """Wraps a secret string with safe repr to prevent accidental leakage.

    The raw value is accessible via .value or str() for API calls,
    but repr() and str() default to [REDACTED].
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


class KeychainSecretProvider:
    """Placeholder for future OS keychain integration.

    Currently always returns None.
    When implemented, this will use:
    - macOS: Keychain
    - Windows: Credential Manager
    - Linux: libsecret / GNOME Keyring
    """

    def get_secret(self, key: str) -> SecretValue | None:
        return None

    def list_keys(self) -> list[str]:
        return []

    def set_secret(self, key: str, value: str) -> None:
        raise NotImplementedError("KeychainSecretProvider not yet implemented")

    def delete_secret(self, key: str) -> bool:
        raise NotImplementedError("KeychainSecretProvider not yet implemented")

    def rotate_secret(self, key: str, new_value: str) -> bool:
        raise NotImplementedError("KeychainSecretProvider not yet implemented")

    def __repr__(self) -> str:
        return "KeychainSecretProvider(placeholder)"
