from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from cogito_agent.shared.redaction import RedactionHelper

_redactor = RedactionHelper()
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_STRONG = re.compile(r"\*\*([^*\n]+)\*\*")
_EMPHASIS = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _STRONG.sub(r"<strong>\1</strong>", escaped)
    escaped = _EMPHASIS.sub(r"<em>\1</em>", escaped)

    def safe_link(match: re.Match[str]) -> str:
        label, url = match.group(1), html.unescape(match.group(2))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return label
        return (
            f'<a href="{html.escape(url, quote=True)}" '
            'target="_blank" rel="noopener noreferrer">'
            f"{label}</a>"
        )

    return _LINK.sub(safe_link, escaped)


def render_safe_markdown(text: str) -> str:
    """Render a deliberately small, escaped Markdown allowlist."""
    safe_text = _redactor.redact(text)
    lines = safe_text.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{'<br>'.join(_inline(line) for line in paragraph)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            output.append("</ul>")
            in_list = False

    for line in lines:
        if line.strip().startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1)) + 2
            output.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        item = re.match(r"^\s*[-*]\s+(.+)$", line)
        if item:
            flush_paragraph()
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append(f"<li>{_inline(item.group(1))}</li>")
            continue
        close_list()
        paragraph.append(line)

    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    flush_paragraph()
    close_list()
    return "".join(output) or "<p></p>"
