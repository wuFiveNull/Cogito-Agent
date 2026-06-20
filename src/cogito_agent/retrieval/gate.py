from __future__ import annotations

from dataclasses import dataclass

from .query import MemoryQueryContext


@dataclass
class RetrievalGateResult:
    mode: str = "hybrid"
    degraded_reason: str = ""
    original_query: str = ""
    enriched_query: str = ""


_GREETING_WORDS = {
    "hi", "hello", "hey", "你好", "早上好", "下午好", "晚上好",
    "ok", "okay", "thanks", "thank", "bye", "再见",
    "好的", "可以", "谢谢", "不用", "没事", "yes", "no", "y", "n",
    "嗯", "哦", "啊", "好的吧",
}

_PROFILE_KEYWORDS = {
    "我喜欢", "我不喜欢", "我的名字", "我的偏好", "我的习惯",
    "我的性格", "我住在", "我工作", "我毕业于",
    "i like", "i love", "i prefer", "i am", "i live",
    "my name", "my preference", "my hobby",
}

_TEMPORAL_KEYWORDS = {
    "上次", "之前", "后来", "曾经", "什么时候", "那次",
    "earlier", "before", "previous", "last", "then", "after",
    "yesterday", "今天", "昨天", "明天",
}

_HISTORY_KEYWORDS = {
    "刚才", "刚刚", "上一条", "前面的", "刚才说的", "上一轮",
    "刚才", "我说过", "你说过", "我记得",
}


class RetrievalGate:
    def evaluate(self, ctx: MemoryQueryContext) -> RetrievalGateResult:
        message = ctx.current_message.strip().lower()
        orig = ctx.original_query or ctx.current_message
        enriched = ctx.context_enriched_query or ctx.current_message

        if not message:
            return RetrievalGateResult(
                mode="no_recall",
                original_query=orig,
                enriched_query=enriched,
            )

        words = message.split()
        if len(words) <= 2 and message in _GREETING_WORDS:
            return RetrievalGateResult(
                mode="resident_only",
                original_query=orig,
                enriched_query=enriched,
            )

        for kw in _PROFILE_KEYWORDS:
            if kw in message:
                return RetrievalGateResult(
                    mode="profile_only",
                    original_query=orig,
                    enriched_query=enriched,
                )

        for kw in _HISTORY_KEYWORDS:
            if kw in message:
                return RetrievalGateResult(
                    mode="timeline",
                    original_query=orig,
                    enriched_query=enriched,
                )

        for kw in _TEMPORAL_KEYWORDS:
            if kw in message:
                return RetrievalGateResult(
                    mode="timeline",
                    original_query=orig,
                    enriched_query=enriched,
                )

        if len(message.rstrip("?.!")) < 3:
            return RetrievalGateResult(
                mode="resident_only",
                original_query=orig,
                enriched_query=enriched,
            )

        return RetrievalGateResult(
            mode="hybrid",
            original_query=orig,
            enriched_query=enriched,
        )
