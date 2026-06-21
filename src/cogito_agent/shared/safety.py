from __future__ import annotations

UNTRUSTED_CONTENT_BEGIN = "UNTRUSTED_CONTENT_BEGIN"
UNTRUSTED_CONTENT_END = "UNTRUSTED_CONTENT_END"


def wrap_untrusted(content: str) -> str:
    return f"{UNTRUSTED_CONTENT_BEGIN}\n{content}\n{UNTRUSTED_CONTENT_END}"


def is_wrapped(content: str) -> bool:
    return content.startswith(UNTRUSTED_CONTENT_BEGIN) and content.endswith(UNTRUSTED_CONTENT_END)


def unwrap_untrusted(content: str) -> str:
    if not is_wrapped(content):
        return content
    start = len(UNTRUSTED_CONTENT_BEGIN) + 1
    end = len(content) - len(UNTRUSTED_CONTENT_END) - 1
    if start >= end:
        return ""
    return content[start:end]
