from __future__ import annotations

from cogito_agent.shared.redaction import RedactionHelper

_redactor = RedactionHelper()


def redact_html(text: str) -> str:
    return _redactor.redact(text)
