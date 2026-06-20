from __future__ import annotations

from cogito_agent.context import ContextItem
from cogito_agent.shared.multimodal import (
    ChatMessage,
    ContentPart,
    ImagePart,
    TextPart,
)
from cogito_agent.shared.safety import (
    wrap_untrusted,
)

SYSTEM_TEMPLATE = (
    "You are a helpful personal assistant running in Cogito-Agent, "
    "a local-first personal agent runtime. You have access to tools, "
    "long-term memory, and governed capabilities. "
    "Respond concisely and helpfully."
)


def _content_parts_from_event_payload(payload: dict[str, object]) -> list[ContentPart]:
    """Convert event payload content to ContentPart list."""
    content_raw = payload.get("content", [])
    if isinstance(content_raw, list):
        parts: list[ContentPart] = []
        for item in content_raw:
            if not isinstance(item, dict):
                continue
            ptype = item.get("type", "text")
            if ptype == "image":
                parts.append(ImagePart.model_validate(item))
            elif ptype == "file":
                from cogito_agent.shared.multimodal import FilePart
                parts.append(FilePart.model_validate(item))
            else:
                parts.append(TextPart(text=str(item.get("text", ""))))
        return parts
    return []


class PromptBuilder:
    """Build model messages from governed context items.

    Receives the output of ContextEngine (already sorted, trimmed,
    budgeted) and converts it into a provider-neutral message list.

    Supports multimodal content: ImagePart and FilePart are preserved
    in the output to support vision-capable models.

    Partitioning (in order):
      1. System policy / agent instruction
      2. Skill instruction (optional)
      3. Retrieved memories (tagged source)
      4. Retrieved workspace sources (files, chunks)
      5. Conversation history
      6. Tool results from current turn
      7. Current user message (with optional multimodal content)

    Messages are deduplicated:
      - current_message may appear in ContextItems — only include once
      - history messages from ContextItems replace redundant DB queries
    """

    def __init__(
        self,
        system_instruction: str = SYSTEM_TEMPLATE,
    ) -> None:
        self._system = system_instruction

    def build(
        self,
        ctx_items: list[ContextItem],
        current_message: str = "",
        tool_results: list[dict[str, object]] | None = None,
        skill_instruction: str = "",
        runtime_metadata: dict[str, str] | None = None,
        extra_content: list[ContentPart] | None = None,
    ) -> list[dict[str, object]]:
        included = [c for c in ctx_items if c.included]
        msgs: list[dict[str, object]] = []

        # 1. System policy
        system_parts = [self._system]
        if skill_instruction:
            system_parts.append(f"\nSkill Context:\n{skill_instruction}")
        msgs.append({"role": "system", "content": "\n".join(system_parts)})

        summary_items = [
            c for c in included if c.source_type == "session_summary"
        ]
        if summary_items:
            msgs.append({
                "role": "system",
                "content": wrap_untrusted(
                    "Conversation Summary:\n" + summary_items[-1].text
                ),
            })

        # 2. Build memory context block
        memory_items = [c for c in included if c.source_type == "memory"]
        if memory_items:
            memory_block = "\n\n".join(
                f"[Memory: {c.source_id}] {c.text}"
                for c in memory_items
            )
            msgs.append({
                "role": "system",
                "content": wrap_untrusted(f"Retrieved Memories:\n{memory_block}"),
            })

        # 3. Workspace file / chunk context
        file_items = [
            c for c in included
            if c.source_type in ("file", "workspace_file", "file_chunk")
        ]
        if file_items:
            file_block = "\n\n".join(
                f"[{c.source_type}: {c.source_id}] {c.text}"
                for c in file_items
            )
            msgs.append({
                "role": "system",
                "content": wrap_untrusted(f"Workspace Sources:\n{file_block}"),
            })

        # 4. Artifact context
        artifact_items = [c for c in included if c.source_type == "artifact"]
        if artifact_items:
            artifact_block = "\n\n".join(c.text for c in artifact_items)
            msgs.append({
                "role": "system",
                "content": wrap_untrusted(f"Artifacts:\n{artifact_block}"),
            })

        # 5. Conversation history (skip current_message items)
        history_items = [
            c for c in included
            if c.source_type in ("message", "conversation")
            and c.source_id != "current"
        ]
        for item in history_items:
            msgs.append({
                "role": "user",
                "content": item.text,
            })

        # 6. Tool results — with image support
        for tr in (tool_results or []):
            raw = str(tr.get("summary", "") or tr.get("error", ""))
            if raw:
                tool_msg: dict[str, object] = {
                    "role": "tool",
                    "content": wrap_untrusted(raw),
                }
                tool_call_id = tr.get("tool_call_id", "")
                if tool_call_id:
                    tool_msg["tool_call_id"] = tool_call_id
                msgs.append(tool_msg)
            # If tool returned an image, inject a user message with the image
            # so the vision model can see it (tool role can't carry images).
            image_b64 = tr.get("image_b64")
            if image_b64:
                mime_type = tr.get("mime_type", "image/png")
                msgs.append({
                    "role": "user",
                    "content": [{
                        "type": "image",
                        "uri": image_b64,
                        "mime_type": mime_type,
                    }],
                })

        # 7. Current user message — with optional multimodal content
        current_in_ctx = any(
            c.source_type == "current_message" and c.included
            for c in ctx_items
        )
        if extra_content:
            legacy_parts = []
            for part in extra_content:
                if isinstance(part, TextPart):
                    legacy_parts.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    legacy_parts.append({
                        "type": "image",
                        "uri": part.uri,
                        "mime_type": part.mime_type,
                    })
                elif isinstance(part, type(ImagePart)) or type(part).__name__ == "ImagePart":
                    legacy_parts.append({
                        "type": "image",
                        "uri": part.uri,
                        "mime_type": getattr(part, "mime_type", "image/png"),
                    })
                else:
                    from cogito_agent.shared.multimodal import FilePart
                    if isinstance(part, FilePart):
                        legacy_parts.append({
                            "type": "file",
                            "uri": part.uri,
                            "mime_type": part.mime_type,
                            "filename": part.filename,
                        })
            if current_message:
                legacy_parts.append({"type": "text", "text": current_message})
            msgs.append({"role": "user", "content": legacy_parts})
        elif current_message and not current_in_ctx:
            msgs.append({"role": "user", "content": current_message})
        elif current_in_ctx:
            cm = next(
                (c for c in ctx_items if c.source_type == "current_message" and c.included),
                None,
            )
            if cm and cm.text:
                msgs.append({"role": "user", "content": cm.text})

        return msgs
