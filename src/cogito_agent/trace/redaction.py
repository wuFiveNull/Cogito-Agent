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
    "RedactionRule", "PatternRule",
    "SecretProvider", "SecretValue",
    "EnvSecretProvider", "KeychainSecretProvider",
    "RedactionHelper",
]


class RedactionHelper:
    def __init__(
        self,
        rules: list[RedactionRule] | None = None,
        secret_providers: list[SecretProvider] | None = None,
    ) -> None:
        self._rules = rules or [
            PatternRule(r"Bearer\s+\S+", "Bearer [REDACTED]"),
            PatternRule(r"sk-[A-Za-z0-9]{20,}", "[REDACTED_API_KEY]"),
            PatternRule(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_API_KEY]"),
            PatternRule(r"sk-\S{8,}", "[REDACTED_API_KEY]"),
            PatternRule(
                r"(?:api[_-]?key|apikey|secret|token|password|credential)"
                r"\s*[:=]\s*['\"]?\S+",
                "[KEY]=[REDACTED]",
            ),
            PatternRule(r"Authorization\s*:\s*\S+", "Authorization: [REDACTED]"),
            PatternRule(r"Cookie\s*:\s*[^;\n]+", "Cookie: [REDACTED]"),
            PatternRule(r"https?://[^:@\s]+:[^@\s]+@", "https://[REDACTED]@"),
            PatternRule(r"(?i)(token|api_key|access_token)=[^&\s]+", r"\1=[REDACTED]"),
            PatternRule(
                r"(?i)(session|auth|xsrf|jwt)[_\-.](token|key|id)\s*[:=]\s*['\"]?\S+",
                r"\1_\2=[REDACTED]",
            ),
        ]
        self._secret_providers = secret_providers or [EnvSecretProvider()]
        self._compile_env_rules()

    def _compile_env_rules(self) -> None:
        """Dynamically add rules from known secrets in environment."""
        for provider in self._secret_providers:
            for key in provider.list_keys():
                sv = provider.get_secret(key)
                if sv is not None and len(sv) > 4:
                    self._rules.append(PatternRule(re.escape(sv.value), "[REDACTED_ENV]"))

    def redact(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        result = text
        for rule in self._rules:
            result = rule.apply(result)
        return result

    def redact_dict(self, obj: object) -> object:
        if isinstance(obj, dict):
            return {k: self.redact_dict(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.redact_dict(v) for v in obj]
        if isinstance(obj, str):
            return self.redact(obj)
        return obj

    def add_rule(self, rule: RedactionRule) -> None:
        self._rules.append(rule)
