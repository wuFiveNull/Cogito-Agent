from __future__ import annotations

import re
import uuid
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str
    source_id: str
    text: str
    rank: int = 0
    token_estimate: int = 0
    included: bool = True
    reason: str = ""
    role: str = ""
    tool_call_id: str = ""
    freshness_score: float = 0.5
    trust_score: float = 0.5
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    stable_ref: str = ""
    exclusion_reason: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.stable_ref:
            self.stable_ref = (
                f"{self.source_type}:{self.source_id}"
                if self.source_id
                else f"{self.source_type}:{self.id}"
            )


class ContextTraceSink(Protocol):
    """Persistence boundary for context selection evidence."""

    def persist_context_items(
        self,
        items: list[ContextItem],
        *,
        trace_id: str,
        workspace_id: str,
    ) -> None: ...


_DEFAULT_BUDGET_SHARES: dict[str, float] = {
    "system": 0.20,
    "recent_messages": 0.25,
    "retrieved_memory": 0.15,
    "memory_file": 0.15,
    "tool_file_context": 0.15,
    "response_reserve": 0.10,
}

# ── Query intent detection patterns ───────────────────────────────────────
# These are lightweight keyword-based classifiers that replace the old
# static budget ratios with dynamic per-query allocation.

_MEMORY_QUERY_PATTERNS = re.compile(
    r"(?:我记得|我上次|之前说过|以前聊过|我记得你|"
    r"what did i say|what was|remember when|"
    r"我之前|之前提到|你记得|你还记得|"
    r"回忆|想起|检索|查一下|查查)",
    re.IGNORECASE,
)

_CODE_TASK_PATTERNS = re.compile(
    r"(?:帮我改|写一个|实现|重构|修复bug|"
    r"code|write a|implement|refactor|fix bug|"
    r"添加功能|优化|写个|写一段|"
    r"def |class |import |from |"
    r"git |npm |pip )",
    re.IGNORECASE,
)

_GREETING_PATTERNS = re.compile(
    r"^(?:你好|hi|hello|hey|在吗|早上好|下午好|晚上好|"
    r"good morning|good afternoon|good evening|"
    r"你叫|你是谁|你是)",
    re.IGNORECASE,
)


def _detect_query_intent(message: str) -> str:
    """Classify the user's current message into an intent category.

    Returns one of: ``"memory_query"``, ``"code_task"``, ``"greeting"``, ``"general"``.
    """
    if not message or not message.strip():
        return "general"
    msg = message.strip()
    if _GREETING_PATTERNS.match(msg):
        return "greeting"
    if _MEMORY_QUERY_PATTERNS.search(msg):
        return "memory_query"
    if _CODE_TASK_PATTERNS.search(msg):
        return "code_task"
    return "general"


def _compute_dynamic_budget_shares(message: str) -> dict[str, float]:
    """Return budget shares tuned for the detected query intent.

    Returns a copy so callers can mutate safely.
    """
    intent = _detect_query_intent(message)
    shares = dict(_DEFAULT_BUDGET_SHARES)

    if intent == "memory_query":
        # Memory-heavy query: boost retrieval, shrink tool/file
        shares["retrieved_memory"] = 0.30
        shares["memory_file"] = 0.20
        shares["tool_file_context"] = 0.05
        shares["recent_messages"] = 0.15
        shares["response_reserve"] = 0.10

    elif intent == "code_task":
        # Code task: boost tool/file context, shrink memory
        shares["tool_file_context"] = 0.30
        shares["memory_file"] = 0.05
        shares["retrieved_memory"] = 0.05
        shares["recent_messages"] = 0.20
        shares["response_reserve"] = 0.10

    elif intent == "greeting":
        # Simple greeting: minimize everything
        shares["system"] = 0.25
        shares["recent_messages"] = 0.15
        shares["retrieved_memory"] = 0.05
        shares["memory_file"] = 0.05
        shares["tool_file_context"] = 0.05
        shares["response_reserve"] = 0.45

    # else "general" → use defaults

    return shares


class ContextEngine:
    def __init__(
        self,
        total_token_budget: int = 4096,
        trace_sink: ContextTraceSink | None = None,
    ) -> None:
        self._budget = total_token_budget
        self._trace_sink = trace_sink

    def build(
        self,
        recent_messages: list[dict[str, object]],
        memories: list[dict[str, object]],
        current_message: str = "",
        tool_results: list[dict[str, object]] | None = None,
        file_context: list[dict[str, object]] | None = None,
        system_text: str = "",
        trace_id: str = "",
        workspace_id: str = "",
        session_summary: dict[str, object] | None = None,
    ) -> list[ContextItem]:
        items: list[ContextItem] = []

        if system_text:
            items.append(
                ContextItem(
                    source_type="system",
                    source_id="",
                    text=system_text,
                    rank=0,
                    token_estimate=self._estimate_tokens(system_text),
                    included=True,
                    reason="system_policy",
                    freshness_score=1.0,
                    trust_score=1.0,
                )
            )

        items.append(
            ContextItem(
                source_type="current_message",
                source_id="",
                text=current_message,
                rank=0,
                token_estimate=self._estimate_tokens(current_message),
                included=True,
                reason="required",
                freshness_score=1.0,
                trust_score=1.0,
            )
        )

        if session_summary and session_summary.get("summary"):
            summary_id = str(session_summary.get("id", ""))
            summary_text = str(session_summary.get("summary", ""))
            items.append(
                ContextItem(
                    source_type="session_summary",
                    source_id=summary_id,
                    text=summary_text,
                    rank=0,
                    token_estimate=self._estimate_tokens(summary_text),
                    reason="derived_incremental_summary",
                    freshness_score=1.0,
                    trust_score=0.7,
                    evidence=[
                        {
                            "through_message_id": session_summary.get("through_message_id", ""),
                            "parent_summary_id": session_summary.get("parent_summary_id", ""),
                        }
                    ],
                )
            )

        # ── memory file sources (priorities 30-55) ─────────────────────

        # Memory v2: memory file context (SELF.md, MEMORY.md, RECENT_CONTEXT.md)
        # is no longer injected from file store. These are now stored in
        # memory_items table and retrieved via the hybrid retrieval pipeline.

        # Memory v2: semantic retrieval is handled by MemoryRetrievalService,
        # not by chunk_index. This block is intentionally removed.

        for i, msg in enumerate(recent_messages):
            text = str(msg.get("content", ""))
            raw_role = msg.get("role", "")
            role = str(raw_role) if isinstance(raw_role, str) else ""
            items.append(
                ContextItem(
                    source_type="message",
                    source_id=str(msg.get("id", "")),
                    text=text,
                    rank=i + 1,
                    token_estimate=self._estimate_tokens(text),
                    role=role,
                    reason="recent_history",
                    freshness_score=self._score(msg, "freshness_score", 1.0),
                    trust_score=self._score(msg, "trust_score", 0.8),
                )
            )
        for i, mem in enumerate(memories):
            text = str(mem.get("text", ""))
            lineage_info = mem.get("lineage_info")
            retrieval_source = str(mem.get("retrieval_source", "retrieved"))
            source_type = (
                "memory_resident" if retrieval_source == "resident" else "memory_retrieved"
            )
            reason = retrieval_source
            if isinstance(lineage_info, dict):
                reason = str(lineage_info.get("reason", reason))
            items.append(
                ContextItem(
                    source_type=source_type,
                    source_id=str(mem.get("id", "")),
                    text=text,
                    rank=i + 1,
                    token_estimate=self._estimate_tokens(text),
                    reason=reason,
                    freshness_score=self._score(mem, "freshness_score", 0.5),
                    trust_score=self._score(
                        mem, "confidence", self._score(mem, "trust_score", 0.5)
                    ),
                    evidence=self._evidence_from(mem),
                )
            )
        for i, tr in enumerate(tool_results or []):
            text = str(tr.get("summary", "") or tr.get("error", ""))
            if text:
                items.append(
                    ContextItem(
                        source_type="tool",
                        source_id=str(tr.get("tool", f"tool_{i}")),
                        text=text,
                        rank=i + 1,
                        token_estimate=self._estimate_tokens(text),
                        reason="tool_result",
                        freshness_score=1.0,
                        trust_score=self._score(tr, "trust_score", 0.7),
                    )
                )
        for i, fc in enumerate(file_context or []):
            text = str(fc.get("text", ""))
            if text:
                items.append(
                    ContextItem(
                        source_type="file",
                        source_id=str(fc.get("id", f"file_{i}")),
                        text=text,
                        rank=i + 1,
                        token_estimate=self._estimate_tokens(text),
                        reason="file_context",
                        freshness_score=self._score(fc, "freshness_score", 0.5),
                        trust_score=self._score(fc, "trust_score", 0.7),
                        evidence=self._evidence_from(fc),
                    )
                )

        items = self._apply_budget_shares(items, current_message)
        items = self._trim(items)

        if self._trace_sink is not None and trace_id and workspace_id:
            self._trace_sink.persist_context_items(
                items,
                trace_id=trace_id,
                workspace_id=workspace_id,
            )
        return items

    def _estimate_tokens(self, text: str) -> int:
        try:
            from cogito_agent.models import token_count

            return token_count(text)
        except Exception:
            char_count = len(text)
            return max(1, char_count // 4)

    def _apply_budget_shares(
        self, items: list[ContextItem], current_message: str = "",
    ) -> list[ContextItem]:
        shares = _compute_dynamic_budget_shares(current_message)
        budgets: dict[str, int] = {}
        for source_type, share in shares.items():
            budgets[source_type] = max(64, int(self._budget * share))
        cat_usage: dict[str, int] = {}
        for item in sorted(items, key=lambda x: x.rank):
            cat = self._category_for_source(item.source_type)
            cat_budget = budgets.get(cat, self._budget)
            used = cat_usage.get(cat, 0)
            if used + item.token_estimate > cat_budget:
                item.included = False
                item.exclusion_reason = f"exceeded_{cat}_budget"
            else:
                cat_usage[cat] = used + item.token_estimate
        return items

    def _category_for_source(self, source_type: str) -> str:
        mapping = {
            "current_message": "system",
            "message": "recent_messages",
            "memory": "retrieved_memory",
            "memory_resident": "retrieved_memory",
            "memory_retrieved": "retrieved_memory",
            "memory_file": "memory_file",
            "tool": "tool_file_context",
            "file": "tool_file_context",
            "skill": "tool_file_context",
            "system": "system",
            "session_summary": "recent_messages",
        }
        return mapping.get(source_type, "recent_messages")

    def _trim(self, items: list[ContextItem]) -> list[ContextItem]:
        total_tokens = sum(i.token_estimate for i in items if i.included)
        if total_tokens <= self._budget:
            return items
        non_essential = [i for i in items if i.source_type not in ("current_message",)]
        non_essential.sort(key=lambda x: (-x.rank, x.token_estimate))
        for item in non_essential:
            if total_tokens <= self._budget:
                break
            if item.source_type == "current_message":
                continue
            total_tokens -= item.token_estimate
            item.included = False
            item.exclusion_reason = "trimmed_budget"
        return items

    @staticmethod
    def _evidence_from(source: dict[str, object]) -> list[dict[str, Any]]:
        evidence = source.get("evidence", [])
        if isinstance(evidence, list):
            normalized = [item for item in evidence if isinstance(item, dict)]
            if normalized:
                return normalized
        lineage = source.get("lineage_info", source.get("source_lineage"))
        if isinstance(lineage, dict):
            return [{str(key): value for key, value in lineage.items()}]
        return []

    @staticmethod
    def _score(source: dict[str, object], key: str, default: float) -> float:
        value = source.get(key, default)
        if isinstance(value, (int, float, str)):
            try:
                return float(value)
            except ValueError:
                return default
        return default


def _strip_recent_turns_section(text: str) -> str:
    """Remove the ``## Recent Turns`` section from RECENT_CONTEXT.md."""
    return re.sub(r"\n?## Recent Turns\n.*", "", text, flags=re.DOTALL).strip()
