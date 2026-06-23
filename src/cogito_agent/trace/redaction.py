from __future__ import annotations

import re
from typing import Protocol

from cogito_agent.security.secrets import (
    EnvSecretProvider,
    KeychainSecretProvider,
    SecretProvider,
    SecretValue,
)


class RedactionRule(Protocol):
    def apply(self, text: str) -> str: ...


class PatternRule:
    def __init__(self, pattern: str, replacement: str = "[REDACTED]") -> None:
        self._pattern = re.compile(pattern, re.IGNORECASE)
        self._replacement = replacement

    def apply(self, text: str) -> str:
        return self._pattern.sub(self._replacement, text)


# Re-export for backward compatibility
__all__ = [
    "RedactionRule",
    "PatternRule",
    "SecretProvider",
    "SecretValue",
    "EnvSecretProvider",
    "KeychainSecretProvider",
    "RedactionHelper",
]

# RedactionHelper moved to cogito_agent.shared.redaction
# This re-export preserves backward compatibility for existing imports.
from cogito_agent.shared.redaction import RedactionHelper  # noqa: E402, F401
