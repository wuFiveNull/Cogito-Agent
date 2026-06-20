from __future__ import annotations

import json
import uuid
from typing import Any

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


BUDGET_SHARES: dict[str, float] = {
    "system": 0.20,
    "recent_messages": 0.30,
    "retrieved_memory": 0.20,
    "tool_file_context": 0.20,
    "response_reserve": 0.10,
}


class ContextEngine:
    def __init__(self, total_token_budget: int = 4096) -> None:
        self._budget = total_token_budget

    def build(
        self,
        recent_messages: list[dict[str, object]],
        memories: list[dict[str, object]],
        current_message: str = "",
        tool_results: list[dict[str, object]] | None = None,
        file_context: list[dict[str, object]] | None = None,
        system_text: str = "",
        db: Any = None,
        trace_id: str = "",
        workspace_id: str = "",
        session_summary: dict[str, object] | None = None,
    ) -> list[ContextItem]:
        items: list[ContextItem] = []

        if system_text:
            items.append(ContextItem(
                source_type="system",
                source_id="",
                text=system_text,
                rank=0,
                token_estimate=self._estimate_tokens(system_text),
                included=True,
                reason="system_policy",
                freshness_score=1.0,
                trust_score=1.0,
            ))

        items.append(ContextItem(
            source_type="current_message",
            source_id="",
            text=current_message,
            rank=0,
            token_estimate=self._estimate_tokens(current_message),
            included=True,
            reason="required",
            freshness_score=1.0,
            trust_score=1.0,
        ))

        if session_summary and session_summary.get("summary"):
            summary_id = str(session_summary.get("id", ""))
            summary_text = str(session_summary.get("summary", ""))
            items.append(ContextItem(
                source_type="session_summary",
                source_id=summary_id,
                text=summary_text,
                rank=0,
                token_estimate=self._estimate_tokens(summary_text),
                reason="derived_incremental_summary",
                freshness_score=1.0,
                trust_score=0.7,
                evidence=[{
                    "through_message_id": session_summary.get(
                        "through_message_id", ""
                    ),
                    "parent_summary_id": session_summary.get(
                        "parent_summary_id", ""
                    ),
                }],
            ))

        for i, msg in enumerate(recent_messages):
            text = str(msg.get("content", ""))
            raw_role = msg.get("role", "")
            role = str(raw_role) if isinstance(raw_role, str) else ""
            items.append(ContextItem(
                source_type="message",
                source_id=str(msg.get("id", "")),
                text=text,
                rank=i + 1,
                token_estimate=self._estimate_tokens(text),
                role=role,
                reason="recent_history",
                freshness_score=self._score(msg, "freshness_score", 1.0),
                trust_score=self._score(msg, "trust_score", 0.8),
            ))
        for i, mem in enumerate(memories):
            text = str(mem.get("text", ""))
            lineage_info = mem.get("lineage_info")
            retrieval_source = str(mem.get("retrieval_source", "retrieved"))
            source_type = "memory_resident" if retrieval_source == "resident" else "memory_retrieved"
            reason = retrieval_source
            if isinstance(lineage_info, dict):
                reason = str(lineage_info.get("reason", reason))
            items.append(ContextItem(
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
            ))
        for i, tr in enumerate(tool_results or []):
            text = str(tr.get("summary", "") or tr.get("error", ""))
            if text:
                items.append(ContextItem(
                    source_type="tool",
                    source_id=str(tr.get("tool", f"tool_{i}")),
                    text=text,
                    rank=i + 1,
                    token_estimate=self._estimate_tokens(text),
                    reason="tool_result",
                    freshness_score=1.0,
                    trust_score=self._score(tr, "trust_score", 0.7),
                ))
        for i, fc in enumerate(file_context or []):
            text = str(fc.get("text", ""))
            if text:
                items.append(ContextItem(
                    source_type="file",
                    source_id=str(fc.get("id", f"file_{i}")),
                    text=text,
                    rank=i + 1,
                    token_estimate=self._estimate_tokens(text),
                    reason="file_context",
                    freshness_score=self._score(fc, "freshness_score", 0.5),
                    trust_score=self._score(fc, "trust_score", 0.7),
                    evidence=self._evidence_from(fc),
                ))

        items = self._apply_budget_shares(items)
        items = self._trim(items)

        self._persist(items, db, trace_id, workspace_id)
        return items

    def _estimate_tokens(self, text: str) -> int:
        try:
            from cogito_agent.models import token_count
            return token_count(text)
        except Exception:
            char_count = len(text)
            return max(1, char_count // 4)

    def _apply_budget_shares(self, items: list[ContextItem]) -> list[ContextItem]:
        budgets: dict[str, int] = {}
        for source_type, share in BUDGET_SHARES.items():
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

    def _persist(
        self, items: list[ContextItem], db: Any, trace_id: str, workspace_id: str
    ) -> None:
        if db is None or not trace_id or not workspace_id:
            return
        for item in items:
            try:
                db.connection.execute(
                    "INSERT INTO context_items"
                    " (id, trace_id, workspace_id, source_type, source_id, rank,"
                    "  token_estimate, included, reason, freshness_score, trust_score,"
                    "  evidence_json, stable_ref, exclusion_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.id, trace_id, workspace_id,
                        item.source_type, item.source_id,
                        item.rank, item.token_estimate,
                        1 if item.included else 0,
                        item.reason,
                        item.freshness_score,
                        item.trust_score,
                        json.dumps(item.evidence),
                        item.stable_ref,
                        item.exclusion_reason,
                    ),
                )
            except Exception:
                pass
        try:
            db.connection.commit()
        except Exception:
            pass
