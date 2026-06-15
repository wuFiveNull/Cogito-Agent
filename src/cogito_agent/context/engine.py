from __future__ import annotations

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
        db: Any = None,
        trace_id: str = "",
        workspace_id: str = "",
    ) -> list[ContextItem]:
        items: list[ContextItem] = []

        items.append(ContextItem(
            source_type="current_message",
            source_id="",
            text=current_message,
            rank=0,
            token_estimate=max(1, len(current_message.split())),
            included=True,
            reason="required",
        ))

        for i, msg in enumerate(recent_messages):
            text = str(msg.get("content", ""))
            items.append(ContextItem(
                source_type="message",
                source_id=str(msg.get("id", "")),
                text=text,
                rank=i + 1,
                token_estimate=max(1, len(text.split())),
                reason="recent_history",
            ))
        for i, mem in enumerate(memories):
            text = str(mem.get("text", ""))
            items.append(ContextItem(
                source_type="memory",
                source_id=str(mem.get("id", "")),
                text=text,
                rank=i + 1,
                token_estimate=max(1, len(text.split())),
                reason="retrieved",
            ))

        items = self._apply_budget_shares(items)
        items = self._trim(items)

        self._persist(items, db, trace_id, workspace_id)
        return items

    def _apply_budget_shares(self, items: list[ContextItem]) -> list[ContextItem]:
        return items

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
            item.reason = "trimmed_budget"
        return items

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
                    "  token_estimate, included, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.id, trace_id, workspace_id,
                        item.source_type, item.source_id,
                        item.rank, item.token_estimate,
                        1 if item.included else 0,
                        item.reason,
                    ),
                )
            except Exception:
                pass
        try:
            db.connection.commit()
        except Exception:
            pass
