from __future__ import annotations

from cogito_agent.trace.redaction import RedactionHelper

_redactor = RedactionHelper()


def redact_html(text: str) -> str:
    return _redactor.redact(text)
