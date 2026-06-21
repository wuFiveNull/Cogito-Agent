from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from cogito_agent.models import ModelAdapter

from .memorizer import Memorizer

logger = logging.getLogger(__name__)

_SUMMARY_MAX_TOKENS = 512


def _format_conversation(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        role = str(m.get("role", "")).upper()
        content = str(m.get("content", "") or "")
        if not content or role in {"TOOL", "SYSTEM"}:
            continue
        ts = str(m.get("created_at", "") or m.get("timestamp", ""))[:16]
        lines.append(f"[{ts}] {role}: {content}")
    return "\n".join(lines)


# ── LLM prompt builders ────────────────────────────────────────────


def _build_recent_context_prompt(
    *,
    old_recent_context: str,
    conversation: str,
    recent_turns: str,
) -> str:
    return f"""你是近期语境压缩代理。你的任务不是自由总结，而是为后续对话保守地抽取近期语境。

目标：
1. 提取用户最近持续关注的话题
2. 提取最近新暴露、但尚未沉淀为长期记忆的显式偏好
3. 提取最近适合自然续接的话题
4. 提取最近应避免打扰、应避免推荐、或明显不想聊的方向
5. 提取跨窗口持续存在的重要现实线索（ongoing_threads）

规则：
- 只允许依据 USER 明确表达过的内容输出；ASSISTANT 的建议、解释、命名、延伸，一律不得当作证据
- active_topics 和 follow_ups 要优先写"话题层级"的概括
- user_preferences 只允许在 USER 出现明确偏好/要求/禁忌表达时输出
- avoidances 只允许在 USER 明确表达"不要/别/避免/不想"时输出
- ongoing_threads 只记录用户正在经历、推进或承受的重要事情
- 每个字段最多 3 条，每条尽量 1 句
- 没有把握就留空；宁可漏掉，也不要脑补

【上一版 recent context】
{old_recent_context or "（空）"}

【较早窗口（本次待压缩）】
{conversation or "（空）"}

【最新 recent turns】
{recent_turns or "（空）"}

返回 JSON：
{{
  "active_topics": [],
  "user_preferences": [],
  "follow_ups": [],
  "avoidances": [],
  "ongoing_threads": []
}}"""


def _build_event_extraction_prompt(
    *,
    conversation: str,
    current_memory: str,
    recent_history_block: str,
) -> str:
    return f"""你是记忆提取代理（Memory Extraction Agent）。从对话中精确提取结构化信息，返回 JSON。

## 字段说明

### 1. "history_entries"（数组，每条对应一个独立主题）
按主题拆分，每个独立话题写一条对象，格式为 {{"summary":"...", "emotional_weight":0}}。
summary 以 [YYYY-MM-DD HH:MM] 开头，保留足够细节便于未来检索。
不同主题必须拆成独立条目，不得合并。

### 2. "pending_items"（候选记忆）
只写用户的长期记忆候选，返回对象数组。每个对象格式：
{{"tag": "<tag>", "content": "<string>"}}

允许的 tag：
- "preference"：稳定偏好、禁忌
- "profile"：稳定背景事实
- "key_info"：用户明确允许保存的 key/token/id
- "health_long_term"：长期健康状态
- "requested_memory"：用户明确要求"长期记住"的内容
- "correction"：对现有记忆的明确纠正
- "general"：其他

若没有合格条目，返回空数组 []。

## 当前用户档案（用于查重）
{current_memory or "（空）"}

## 待处理对话
{conversation}

只返回合法 JSON，不要 markdown 代码块。"""


class ConsolidationService:
    """Post-turn memory consolidation using structured memory_items (Memory v2).

    After each conversation turn:
    1. LLM extraction of history_entries → ``Memorizer.save()`` → memory_items
    2. LLM compression of recent context → RECENT_CONTEXT.md (simplified)
    3. Trim old messages from session (sliding window)

    No longer writes to MEMORY.md / HISTORY.md / PENDING.md files.
    All structured memories go through Memorizer into memory_items table.
    """

    def __init__(
        self,
        memorizer: Memorizer,
        workspace_path: str = "",
        model_adapter: ModelAdapter | None = None,
        *,
        keep_count: int = 20,
        light_model_adapter: ModelAdapter | None = None,
    ) -> None:
        self._memorizer = memorizer
        self._workspace_path = workspace_path
        self._model = model_adapter
        self._light_model = light_model_adapter or model_adapter
        self._keep_count = max(4, keep_count)
        self._consolidation_min_new = max(5, self._keep_count // 2)
        self._threshold = self._keep_count + self._consolidation_min_new

        # per-workspace state
        self._last_consolidated: dict[str, int] = {}

        # sliding window trim callback (set externally)
        self._trim_callback: Any = None

    def set_trim_callback(self, callback: Any) -> None:
        """Set a callback for sliding-window message trim.

        The callback is called with ``(workspace_id, session_id, keep_count)``.
        """
        self._trim_callback = callback

    # ── public API ─────────────────────────────────────────────────────

    def after_turn(
        self,
        messages: list[dict[str, Any]],
        workspace_id: str,
        session_id: str = "",
    ) -> None:
        """Must be called after every completed turn.

        Safe to call even when the memorizer or model is unavailable — all
        failures are caught and logged.
        """
        prev_count = self._last_consolidated.get(workspace_id, 0)
        latest_count = len(messages)

        # Step 1: LLM extraction + Memorizer write if threshold reached
        try:
            if self._model and self._should_consolidate(messages, prev_count):
                self._extract_and_write(messages, prev_count, workspace_id, session_id)
        except Exception:
            logger.exception("Consolidation extraction failed")

        # Step 2: advance counter
        self._last_consolidated[workspace_id] = latest_count

    # ── consolidation decision ────────────────────────────────────────

    def _should_consolidate(
        self, messages: list[dict[str, Any]], prev_count: int
    ) -> bool:
        if not self._model:
            return False
        latest = len(messages)
        new_count = latest - prev_count
        return new_count >= self._consolidation_min_new

    @property
    def needs_consolidation(self) -> bool:
        """Check if any workspace has a consolidation backlog.

        Used by the memory context guard to block turns.
        """
        return False  # checked dynamically per workspace via threshold check

    def consolidation_backlog(self, workspace_id: str, message_count: int) -> int:
        """Return the number of unconsolidated messages for a workspace."""
        prev = self._last_consolidated.get(workspace_id, 0)
        return max(0, message_count - prev)

    # ── async maintenance queue (removed — all consolidation is synchronous) ──

    # ── synchronous LLM consolidation (called from after_turn) ────────

    def _extract_and_write(
        self,
        messages: list[dict[str, Any]],
        prev_count: int,
        workspace_id: str,
        session_id: str = "",
    ) -> None:
        """Run LLM extraction + Memorizer write synchronously.

        Called from after_turn() when threshold is met.
        Output goes to memory_items table via Memorizer, not to files.
        """
        if not self._model or not self._light_model:
            return

        window = messages[prev_count:]
        msg_ids = [str(m.get("id", "")) for m in window if m.get("id")]
        if not msg_ids:
            return

        # Step A: LLM extraction (history_entries + pending_items)
        data = self._call_extraction_llm(window)
        if data:
            if data.get("history_entries"):
                for entry in data["history_entries"]:
                    summary = (entry.get("summary") or "").strip()
                    if not summary:
                        continue
                    ew = int(entry.get("emotional_weight", 0) or 0)
                    self._memorizer.save(
                        summary=summary,
                        memory_type="event",
                        workspace_id=workspace_id,
                        source_ref=session_id,
                        emotional_weight=ew,
                    )
            if data.get("pending_items"):
                for item in data["pending_items"]:
                    content = (item.get("content") or "").strip()
                    tag = str(item.get("tag", "general"))
                    if not content:
                        continue
                    mem_type = {
                        "preference": "preference",
                        "profile": "profile",
                        "key_info": "profile",
                        "health_long_term": "profile",
                        "requested_memory": "profile",
                        "correction": "profile",
                        "task": "task",
                        "general": "general",
                    }.get(tag, "general")
                    self._memorizer.save(
                        summary=content,
                        memory_type=mem_type,
                        workspace_id=workspace_id,
                        source_ref=session_id,
                    )

        # Step B: LLM compression of recent context (simplified, no RECENT_CONTEXT.md)
        self._compress_recent_context(window, workspace_id)

    def _call_extraction_llm(
        self, window: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not self._model:
            return None
        text = _format_conversation(window)
        # Memory v2: read existing active memories for dedup context from memory_items
        memory_context = ""
        try:
            rows = self._memorizer._db.connection.execute(
                "SELECT summary FROM memory_items WHERE status = 'active'"
                " ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()
            if rows:
                memory_context = "\n".join(
                    f"- [{r['summary'][:80]}]" for r in rows if r["summary"]
                )
        except Exception:
            pass

        prompt = _build_event_extraction_prompt(
            conversation=text,
            current_memory=memory_context or "（空）",
            recent_history_block="",
        )

        try:
            resp = self._model.chat([{"role": "user", "content": prompt}])
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0]
            return json.loads(raw)
        except Exception:
            logger.exception("LLM extraction call failed")
            return None

    def _compress_recent_context(
        self,
        window: list[dict[str, Any]],
        workspace_id: str,
    ) -> None:
        """LLM-compress recent conversation context.

        Stores the structured fields in memory_items with type ``_recent_context``,
        replacing the old RECENT_CONTEXT.md file write.
        """
        if not self._light_model:
            return

        conversation = _format_conversation(window)
        if not conversation.strip():
            return

        prompt = _build_recent_context_prompt(
            old_recent_context="（新建）",
            conversation=conversation,
            recent_turns="",
        )
        compression: dict[str, list[str]] | None = None
        try:
            resp = self._light_model.chat(
                [
                    {
                        "role": "system",
                        "content": "你是近期语境压缩代理，只返回合法 JSON。",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=_SUMMARY_MAX_TOKENS,
            )
            text = resp.content.strip()
            if text:
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1]
                    text = text.rsplit("```", 1)[0]
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    compression = {
                        key: [
                            str(item).strip()
                            for item in (parsed.get(key) or [])
                            if str(item).strip()
                        ][:3]
                        for key in (
                            "active_topics", "user_preferences",
                            "follow_ups", "avoidances", "ongoing_threads",
                        )
                    }
        except Exception:
            logger.exception("LLM recent-context compression failed")

        if compression:
            import json as _json
            self._memorizer.save(
                summary=_json.dumps(compression, ensure_ascii=False),
                memory_type="_recent_context",
                workspace_id=workspace_id,
            )

    # ── sliding window trim ───────────────────────────────────────────

    def get_trim_point(self, workspace_id: str, message_count: int) -> int:
        """Return the index up to which messages can be trimmed."""
        prev = self._last_consolidated.get(workspace_id, 0)
        if prev <= 0:
            return 0
        if message_count > self._keep_count + prev:
            return max(0, message_count - self._keep_count)
        return 0

    def needs_guard_consolidation(
        self, workspace_id: str, message_count: int
    ) -> bool:
        """Check if too many unconsolidated messages have accumulated.

        Returns True when backlog exceeds threshold, meaning the turn
        should be blocked until consolidation catches up.
        """
        prev = self._last_consolidated.get(workspace_id, 0)
        pending = message_count - prev
        return pending > self._threshold


# ── (module-level helpers removed — unused since Memory v2) ──────────
