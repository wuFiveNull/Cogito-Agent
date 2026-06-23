"""Memory injection block formatting.

Transforms retrieved memory items into a structured, formatted text block
suitable for LLM context injection. Follows the Akashic pattern of organizing
memories by type with confidence labels, source references, and character
budget enforcement.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_INJECT_MAX_CHARS = 1200
_INJECT_MAX_FORCED = 3
_INJECT_MAX_PROCEDURE_PREFERENCE = 4
_INJECT_MAX_EVENT_PROFILE = 2
_INJECT_LINE_MAX = 180
_HIGH_INJECT_DELTA = 0.15


class MemoryInjectionBuilder:
    """Build a structured injection block from retrieved memory items.

    Segments memories into sections by type:
    - **Forced constraints**: procedure items with tool_requirement (must-execute)
    - **User preferences & rules**: procedure/preference items
    - **Relevant history**: event/profile items

    Each item includes confidence labels, timestamps, and source references.
    The forced-constraint section is never truncated.
    """

    def __init__(
        self,
        max_chars: int = _INJECT_MAX_CHARS,
        max_forced: int = _INJECT_MAX_FORCED,
        max_procedure_preference: int = _INJECT_MAX_PROCEDURE_PREFERENCE,
        max_event_profile: int = _INJECT_MAX_EVENT_PROFILE,
        line_max: int = _INJECT_LINE_MAX,
        high_inject_delta: float = _HIGH_INJECT_DELTA,
    ) -> None:
        self._max_chars = max_chars
        self._max_forced = max_forced
        self._max_procedure_preference = max_procedure_preference
        self._max_event_profile = max_event_profile
        self._line_max = line_max
        self._high_inject_delta = high_inject_delta

    def build(
        self,
        items: list[dict[str, Any]],
        type_thresholds: dict[str, float] | None = None,
    ) -> tuple[str, list[str]]:
        """Build formatted injection block from retrieved items.

        Args:
            items: Retrieved memory items with keys: id, text, type, _score_breakdown
            type_thresholds: Per-type score thresholds (procedure/preference/event/profile)

        Returns:
            (formatted_text_block, list_of_injected_memory_ids)
        """
        if not items:
            return "", []

        thresholds = type_thresholds or {}
        default_th = thresholds.get("_default", 0.0)
        type_th = {
            "procedure": thresholds.get("procedure", default_th),
            "preference": thresholds.get("preference", default_th),
            "event": thresholds.get("event", default_th),
            "profile": thresholds.get("profile", default_th),
        }

        sorted_items = sorted(
            items,
            key=lambda x: float(
                x.get("_score_breakdown", {}).get("final_score", 0.0) or x.get("_rrf_score", 0.0)
            ),
            reverse=True,
        )

        forced: list[tuple[str, str]] = []
        norms: list[tuple[str, str]] = []
        events: list[tuple[str, str]] = []
        forced_count = 0
        norm_count = 0
        event_count = 0
        all_selected_ids: list[str] = []

        for item in sorted_items:
            mem_id = str(item.get("id", "") or item.get("memory_id", "") or "")
            mem_type = str(item.get("type", "general"))
            text = str(item.get("text", "") or item.get("summary", "") or "").strip()
            if not mem_id or not text:
                continue

            score_breakdown = item.get("_score_breakdown", {})
            final_score = float(score_breakdown.get("final_score", 0.0) or 0.0)

            extra_json = item.get("extra_json") or {}
            tool_requirement = extra_json.get("tool_requirement") if isinstance(extra_json, dict) else None

            # Forced: procedure with tool_requirement
            if mem_type == "procedure" and tool_requirement:
                if forced_count >= self._max_forced:
                    continue
                forced_count += 1
                line = self._format_line(text, mem_type, final_score, type_th, item)
                forced.append((mem_id, line))
                all_selected_ids.append(mem_id)
                continue

            # Per-type threshold check
            min_th = type_th.get(mem_type, default_th)
            if final_score < min_th:
                continue

            # Type-specific quota
            if mem_type in ("procedure", "preference"):
                if norm_count >= self._max_procedure_preference:
                    continue
                norm_count += 1
            elif mem_type in ("event", "profile"):
                if event_count >= self._max_event_profile:
                    continue
                event_count += 1
            else:
                continue

            line = self._format_line(text, mem_type, final_score, type_th, item)
            if mem_type in ("procedure", "preference"):
                norms.append((mem_id, line))
            else:
                events.append((mem_id, line))
            all_selected_ids.append(mem_id)

        # Build sections
        parts: list[str] = []
        injected_ids: list[str] = []
        total_chars = 0

        # Forced section — never truncated
        if forced:
            forced_block = "## 【强制约束】必须执行的记忆规则\n" + "\n".join(
                f"  {line}" for _, line in forced
            )
            parts.append(forced_block)
            total_chars += len(forced_block)
            injected_ids.extend(mid for mid, _ in forced)

        # Norms section
        if norms:
            norm_block = "## 【流程规范】用户偏好与规则\n" + "\n".join(
                f"  {line}" for _, line in norms
            )
            budget_left = self._max_chars - total_chars
            if budget_left <= 0:
                pass  # skip — budget exhausted by forced
            elif len(norm_block) <= budget_left:
                parts.append(norm_block)
                total_chars += len(norm_block)
                injected_ids.extend(mid for mid, _ in norms)
            else:
                # Truncate norms if needed
                truncated = self._truncate_section(
                    "## 【流程规范】用户偏好与规则\n",
                    [line for _, line in norms],
                    budget_left,
                )
                if truncated:
                    parts.append(truncated)
                    # Count how many lines fit
                    char_used = total_chars
                    for mid, line in norms:
                        line_len = len(f"  {line}\n")
                        if char_used + line_len > self._max_chars:
                            break
                        char_used += line_len
                        injected_ids.append(mid)
                    total_chars = char_used

        # Events section
        if events:
            event_block = "## 【相关历史】过往对话与画像\n" + "\n".join(
                f"  {line}" for _, line in events
            )
            budget_left = self._max_chars - total_chars
            if budget_left <= 0:
                pass
            elif len(event_block) <= budget_left:
                parts.append(event_block)
                total_chars += len(event_block)
                injected_ids.extend(mid for _, mid in events)
            else:
                truncated = self._truncate_section(
                    "## 【相关历史】过往对话与画像\n",
                    [line for _, line in events],
                    budget_left,
                )
                if truncated:
                    parts.append(truncated)

        return "\n\n".join(parts), injected_ids

    def _format_line(
        self,
        text: str,
        mem_type: str,
        score: float,
        type_th: dict[str, float],
        item: dict[str, Any],
    ) -> str:
        """Format a single memory item line with metadata."""
        # Truncate long text
        if len(text) > self._line_max:
            text = text[: self._line_max - 3] + "..."

        # Confidence label
        type_base = type_th.get(mem_type, 0.0)
        confidence_label = ""
        if type_base > 0 and score < type_base + self._high_inject_delta:
            confidence_label = "有印象，不确定"

        # Timestamp
        happened_at = item.get("happened_at") or item.get("created_at") or ""
        ts = ""
        if happened_at:
            try:
                from datetime import UTC, datetime

                dt = datetime.fromisoformat(str(happened_at))
                ts = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                ts = str(happened_at)[:16]

        parts: list[str] = [text]
        if confidence_label:
            parts.append(f"[{confidence_label}]")
        if ts:
            parts.append(f"({ts})")
        return " ".join(parts)

    @staticmethod
    def _truncate_section(
        header: str,
        lines: list[str],
        budget: int,
    ) -> str:
        """Fit as many lines as possible within the character budget."""
        result = header
        for line in lines:
            candidate = result + f"  {line}\n"
            if len(candidate) > budget:
                break
            result = candidate
        return result if result != header else ""
