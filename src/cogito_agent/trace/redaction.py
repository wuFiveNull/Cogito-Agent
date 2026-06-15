from __future__ import annotations

import re
from typing import Protocol


class RedactionRule(Protocol):
    def apply(self, text: str) -> str: ...


class PatternRule:
    def __init__(self, pattern: str, replacement: str = "[REDACTED]") -> None:
        self._pattern = re.compile(pattern, re.IGNORECASE)
        self._replacement = replacement

    def apply(self, text: str) -> str:
        return self._pattern.sub(self._replacement, text)


class ApiKeyRule:
    def apply(self, text: str) -> str:
        return PatternRule(
            r"(api[_-]?key|apikey|secret|token)\s*[:=]\s*['\"]?\S+",
            r"\1=[REDACTED]",
        ).apply(text)


class RedactionHelper:
    DEFAULT_RULES: list[RedactionRule] = [
        ApiKeyRule(),
        PatternRule(r"sk-[A-Za-z0-9]{20,}", "[REDACTED_API_KEY]"),
        PatternRule(r"Bearer\s+\S+", "Bearer [REDACTED]"),
    ]

    def __init__(self, rules: list[RedactionRule] | None = None) -> None:
        self._rules = rules or list(self.DEFAULT_RULES)

    def redact(self, text: str) -> str:
        result = text
        for rule in self._rules:
            result = rule.apply(result)
        return result

    def add_rule(self, rule: RedactionRule) -> None:
        self._rules.append(rule)
