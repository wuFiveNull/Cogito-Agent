from __future__ import annotations

import json
import logging
from typing import Any

from cogito_agent.memory.ports import LLMExtractionPort
from cogito_agent.models import ModelAdapter

logger = logging.getLogger(__name__)

_SUMMARY_MAX_TOKENS = 512


def _build_extraction_prompt(
    conversation: str,
    memory_context: str,
) -> str:
    """Build the LLM prompt for memory-event extraction."""
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
{memory_context or "（空）"}

## 待处理对话
{conversation}

只返回合法 JSON，不要 markdown 代码块。"""


def _build_compression_prompt(conversation: str) -> str:
    """Build the LLM prompt for recent-context compression."""
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

【待压缩对话】
{conversation or "（空）"}

返回 JSON：
{{
  "active_topics": [],
  "user_preferences": [],
  "follow_ups": [],
  "avoidances": [],
  "ongoing_threads": []
}}"""


def _parse_json(text: str) -> dict[str, Any] | None:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    if not text:
        return None
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        logger.exception("Failed to parse LLM JSON output")
        return None


class LLMExtractionImpl:
    """Concrete implementation of ``LLMExtractionPort`` using ``ModelAdapter``.

    Lives in the ``runtime`` package so that model dependencies are not
    leaked into the ``memory`` layer.
    """

    def __init__(
        self,
        model: ModelAdapter | None,
        light_model: ModelAdapter | None = None,
    ) -> None:
        self._model = model
        self._light_model = light_model or model

    def extract_memories(
        self,
        conversation_text: str,
        memory_context: str = "",
    ) -> dict[str, Any] | None:
        if not self._model:
            return None
        if not conversation_text.strip():
            return None
        prompt = _build_extraction_prompt(conversation_text, memory_context)
        try:
            resp = self._model.chat([{"role": "user", "content": prompt}])
            return _parse_json(resp.content)
        except Exception:
            logger.exception("LLM extraction call failed")
            return None

    def compress_context(
        self,
        conversation_text: str,
    ) -> dict[str, list[str]] | None:
        if not self._light_model:
            return None
        if not conversation_text.strip():
            return None
        prompt = _build_compression_prompt(conversation_text)
        try:
            resp = self._light_model.chat(
                [
                    {"role": "system", "content": "你是近期语境压缩代理，只返回合法 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=_SUMMARY_MAX_TOKENS,
            )
            parsed = _parse_json(resp.content)
            if not isinstance(parsed, dict):
                return None
            return {
                key: [str(item).strip() for item in (parsed.get(key) or []) if str(item).strip()][:3]
                for key in (
                    "active_topics", "user_preferences",
                    "follow_ups", "avoidances", "ongoing_threads",
                )
            }
        except Exception:
            logger.exception("LLM context compression call failed")
            return None
