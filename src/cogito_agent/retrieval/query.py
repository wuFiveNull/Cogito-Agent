from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MemoryQueryContext:
    current_message: str
    recent_user_messages: list[str] = field(default_factory=list)
    session_topic_summary: str = ""
    workspace_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    detected_entities: list[str] = field(default_factory=list)
    temporal_hints: list[str] = field(default_factory=list)
    original_query: str = ""
    context_enriched_query: str = ""
    sparse_safe_query: str = ""


_ENTITY_PATTERN = re.compile(
    r"(?:^|\s)([A-Z][a-z]+(?:[A-Z][a-z]+)*)"
    r"|`([^`]+)`"
    r"|([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)"
)

_TEMPORAL_PATTERNS = [
    re.compile(r"(上次|之前|后来|曾经|什么时候|那次|earlier|before|previous|last|then|after)"),
]

_GREETING_PATTERNS = [
    re.compile(r"^(hi|hello|hey|你好|早上好|下午好|晚上好)\b", re.I),
    re.compile(r"^(好的|可以|谢谢|不用|没事|ok|okay|thanks|thank you|bye|再见)\b", re.I),
    re.compile(r"^[?.!,\s]*$"),
]

_PROFILE_PATTERNS = [
    re.compile(
        r"(我喜欢|我不喜欢|我的名字|我的偏好|我的习惯|我的性格|我住在|我工作在|我毕业于)", re.I
    ),
    re.compile(r"(my name|my preference|i like|i love|i prefer|i am|i live)", re.I),
]

_PROJECT_TASK_PATTERNS = [
    re.compile(r"(项目|任务|功能|bug|feature|issue|PR|分支|branch|repo|仓库)", re.I),
    re.compile(r"(project|task|deadline|milestone|sprint)", re.I),
]


class MemoryQueryBuilder:
    MAX_QUERY_LENGTH = 1024

    def build(
        self,
        current_message: str,
        recent_user_messages: list[str] | None = None,
        session_topic_summary: str = "",
        workspace_id: str = "",
        session_id: str = "",
    ) -> MemoryQueryContext:
        ctx = MemoryQueryContext(
            current_message=current_message,
            recent_user_messages=recent_user_messages or [],
            session_topic_summary=session_topic_summary,
            workspace_id=workspace_id,
            session_id=session_id,
        )

        ctx.original_query = self._build_original_query(ctx)
        ctx.context_enriched_query = self._build_enriched_query(ctx)
        ctx.sparse_safe_query = self._sanitize_for_sparse(ctx.context_enriched_query)
        ctx.detected_entities = self._extract_entities(ctx.context_enriched_query)
        ctx.temporal_hints = self._detect_temporal_hints(ctx.context_enriched_query)

        return ctx

    def _build_original_query(self, ctx: MemoryQueryContext) -> str:
        return ctx.current_message.strip()

    def _build_enriched_query(self, ctx: MemoryQueryContext) -> str:
        parts: list[str] = [ctx.current_message.strip()]

        for recent in ctx.recent_user_messages[-2:]:
            text = recent.strip()
            if text and text not in parts:
                parts.append(text)

        if ctx.session_topic_summary:
            summary = ctx.session_topic_summary.strip()
            if summary and len(summary) < 200:
                parts.append(summary)

        combined = " ".join(parts)
        return combined[: self.MAX_QUERY_LENGTH]

    def _sanitize_for_sparse(self, query: str) -> str:
        sanitized = re.sub(r"[\'\"\(\)\*\:\-\+]", " ", query)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized[: self.MAX_QUERY_LENGTH]

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        matches = _ENTITY_PATTERN.findall(text)
        entities: list[str] = []
        for match in matches:
            for group in match:
                if group:
                    entities.append(group)
        return entities

    @staticmethod
    def _detect_temporal_hints(text: str) -> list[str]:
        hints: list[str] = []
        for pattern in _TEMPORAL_PATTERNS:
            for match in pattern.finditer(text):
                hints.append(match.group(0))
        return hints
