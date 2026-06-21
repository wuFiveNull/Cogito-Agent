from __future__ import annotations

import json
import logging
from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.models import ModelAdapter
from cogito_agent.storage import Database




logger = logging.getLogger(__name__)


class MemoryOptimizer:
    """Background task that merges PENDING.md into MEMORY.md using the LLM.

    Typical scheduled interval: every 18 hours (configurable).
    """

    def __init__(
        self,
        store: MarkdownMemoryStore,
        model_adapter: ModelAdapter,
        db: Database | None = None,
        chunk_index: MarkdownChunkIndex | None = None,
        audit: AuditLogger | None = None,
        workspace_id: str = "default",
    ) -> None:
        self._store = store
        self._model = model_adapter
        self._db = db
        self._chunk_index = chunk_index
        self._audit = audit or (AuditLogger(db) if db else None)
        self._workspace_id = workspace_id

    # ── public API ────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """Single optimizer cycle.

        Returns summary dict with keys: pending_count, memory_changed,
        self_changed, error (if any).
        """
        result: dict[str, Any] = {
            "pending_count": 0,
            "memory_changed": False,
            "self_changed": False,
            "error": None,
        }

        # Step 1: snapshot PENDING
        if not self._store.snapshot_pending():
            return result

        pending = self._store.read_pending_snapshot()
        result["pending_count"] = len(pending)
        if not pending:
            self._store.commit_pending_snapshot()
            return result

        # Step 2: LLM merge into MEMORY.md
        old_memory = self._store.read_memory()
        prompt = (
            "当前长期记忆：\n"
            f"{old_memory}\n\n"
            "待归档新事实：\n"
            f"{_format_pending(pending)}\n\n"
            "请将新事实合并到长期记忆中。规则：\n"
            "- 新事实追加到对应 section\n"
            "- 如果与已有条目冲突，替换旧条目\n"
            "- `correction` tag 覆盖旧条目\n"
            "- 重复忽略\n"
            "- 时间敏感、临时状态丢弃\n"
            "输出完整的新 MEMORY.md 内容（不要用代码块包裹）。"
        )

        try:
            resp = self._model.chat([{"role": "user", "content": prompt}])
            new_memory = resp.content.strip()
            if new_memory.startswith("```"):
                new_memory = new_memory.split("\n", 1)[-1]
                new_memory = new_memory.rsplit("```", 1)[0].strip()
            self._store.backup_memory()
            self._store.write_memory(new_memory)
            self._store.commit_pending_snapshot()
            result["memory_changed"] = True
        except Exception as exc:
            self._store.rollback_pending_snapshot()
            result["error"] = str(exc)
            logger.exception("Memory merge failed, PENDING rolled back")
            return result

        # Step 3: reindex FTS5 if chunk_index available
        if self._chunk_index and self._db:
            try:
                merged = self._store.read_memory()
                self._chunk_index.reindex(merged, self._workspace_id)
            except Exception:
                logger.exception("FTS5 reindex after optimize failed")

        # Step 4: update SELF.md
        try:
            current_self = self._store.read_self()
            recent_history = self._store.read_history(limit=10)
            prompt2 = (
                "当前自我认知：\n"
                f"{current_self}\n\n"
                "近期事件：\n"
                f"{recent_history}\n\n"
                "请更新自我认知。只改动 3 个 section：\n"
                "1. 人格与形象 — 不变或微调\n"
                "2. 我对当前用户的理解 — 从近期事件中提取新的理解\n"
                "3. 我们关系的定义 — 不变或微调\n"
                "不要添加新的 section。无变化则输出原有内容。"
            )
            resp2 = self._model.chat([{"role": "user", "content": prompt2}])
            new_self = resp2.content.strip()
            if new_self.startswith("```"):
                new_self = new_self.split("\n", 1)[-1]
                new_self = new_self.rsplit("```", 1)[0].strip()
            self._store.write_self(new_self)
            result["self_changed"] = True
        except Exception:
            logger.exception("SELF.md update failed (non-fatal)")

        # Step 5: audit
        if self._audit:
            try:
                self._audit.log(
                    actor_id="system",
                    action="memory.optimize",
                    resource="memory",
                    workspace_id=self._workspace_id,
                    decision="allow",
                    reason=f"merged {result['pending_count']} items",
                )
            except Exception:
                pass

        return result


def _format_pending(pending: list[dict[str, Any]]) -> str:
    lines = []
    for item in pending:
        tag = item.get("tag", "general")
        content = item.get("content", "").strip()
        if content:
            lines.append(f"- [{tag}] {content}")
    return "\n".join(lines) if lines else "(empty)"
