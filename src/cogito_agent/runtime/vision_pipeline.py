"""Self-contained vision processing pipeline.

Extracted from ``RuntimeKernel`` to reduce its size and clarify ownership
of image-attachment resolution and vision-model invocation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from cogito_agent.models import ModelAdapter
from cogito_agent.models.messages import (
    ImagePart,
    TextPart,
    has_image,
)
from cogito_agent.models.messages import (
    extract_text as _extract_text_from_parts,
)
from cogito_agent.runtime.ports import (
    RuntimeTracePort,
    VisionObservationPort,
)

logger = logging.getLogger(__name__)


class VisionPipeline:
    """Resolve image attachments and delegate to a vision model or service.

    The caller (``RuntimeKernel``) injects its dependencies so that this
    class has no knowledge of kernel internals.
    """

    def __init__(
        self,
        model_adapter: ModelAdapter | None = None,
        vision_service: VisionObservationPort | None = None,
        tracer: RuntimeTracePort | None = None,
        bind_route_observer: Any = None,
    ) -> None:
        self._model_adapter = model_adapter
        self._vision_service = vision_service
        self._tracer = tracer
        self._bind_route_observer = bind_route_observer or (lambda *a, **kw: None)

    def get_route_observer(self) -> Any:
        """Return the route observer closure for use by the kernel."""
        return self._bind_route_observer

    def resolve_attachments(
        self,
        extra_content: list[Any],
        workspace_id: str,
    ) -> list[Any]:
        """Resolve ImagePart.attachment_id references to data URIs."""
        from cogito_agent.media import MediaProcessor

        resolved: list[Any] = []
        for part in extra_content:
            if isinstance(part, ImagePart) and part.attachment_id and not part.uri:
                if self._vision_service:
                    try:
                        att = self._vision_service.require_attachment(
                            part.attachment_id, workspace_id,
                        )
                        raw = self._vision_service.read_attachment_bytes(att)
                        proc = MediaProcessor()
                        prepared = proc.validate_and_prepare(raw, filename=att.original_filename)
                        data_uri = proc.to_data_uri(prepared)
                        resolved.append(
                            ImagePart(
                                uri=data_uri,
                                mime_type=prepared.mime_type,
                                width=prepared.width,
                                height=prepared.height,
                                attachment_id=part.attachment_id,
                            )
                        )
                    except Exception:
                        resolved.append(
                            TextPart(text=f"[Attachment {part.attachment_id}: failed to load]")
                        )
                else:
                    resolved.append(TextPart(text=f"[Attachment {part.attachment_id}]"))
            else:
                resolved.append(part)
        return resolved

    def build_vision_context(
        self,
        extra_content: list[Any],
        workspace_id: str,
        session_id: str,
    ) -> str:
        """Build vision observation context string for prompt injection."""
        if not self._vision_service:
            return ""
        attachment_ids: list[str] = []
        for part in extra_content or []:
            if isinstance(part, ImagePart) and part.attachment_id:
                attachment_ids.append(part.attachment_id)
        if not attachment_ids:
            return ""
        try:
            return self._vision_service.format_observations_for_context(
                attachment_ids, workspace_id,
            )
        except Exception:
            return ""

    def supports_vision(self) -> bool:
        """Check if the primary model adapter supports vision natively."""
        adapter = self._model_adapter
        if adapter is None:
            return False
        router = getattr(adapter, "_router", None)
        if router is None:
            return False
        candidates = getattr(router, "_candidates", {})
        return any(
            "image" in c.input_modalities or "vision" in c.capabilities
            for c in candidates.values()
        )

    def run_pipeline(
        self,
        extra_content: list[Any],
        user_text: str,
        trace: object,
        span: object,
        event: Any = None,
    ) -> tuple[list[Any], str]:
        """If images present, run vision analysis and return (text_content, message).

        Returns a tuple of (modified_content, text_without_images).
        If no images present, returns (extra_content, user_text) unchanged.
        """
        if not has_image(extra_content) or self._model_adapter is None:
            return extra_content, user_text

        image_parts = [p for p in extra_content if isinstance(p, ImagePart)]
        text_parts = [p for p in extra_content if not isinstance(p, ImagePart)]
        primary_text = _extract_text_from_parts(text_parts) or user_text

        # Dedicated vision service path
        if self._vision_service is not None and self._vision_service.has_vision_capability:
            try:
                self._vision_service.set_current_context(
                    workspace_id=(event.workspace_id if event else ""),
                    trace_id=str(getattr(trace, "id", "")),
                )
                results: list[str] = []
                for img_part in image_parts:
                    att_id = getattr(img_part, "attachment_id", None) or ""
                    if not att_id:
                        continue
                    result = self._vision_service.inspect_image(
                        attachment_id=att_id,
                        prompt=primary_text or "Describe this image",
                        workspace_id=(event.workspace_id if event else ""),
                        trace_id=str(getattr(trace, "id", "")),
                    )
                    if result:
                        results.append(result)

                if results:
                    return text_parts, primary_text
            except Exception as exc:
                logger.warning("Vision service pipeline failed, falling back: %s", exc)

        # Fallback: use primary model adapter for vision
        try:
            call_start = datetime.now(UTC)
            vision_msgs = self._build_vision_messages(image_parts, primary_text)
            self._bind_route_observer(event, trace, span)
            vision_resp = self._model_adapter.chat(
                vision_msgs,
                _route_role="vision_worker",
                _route_task_kind="vision_understanding",
            )
            if self._tracer:
                trace_id = str(getattr(trace, "id", ""))
                span_id = str(getattr(span, "id", ""))
                self._tracer.log_model_call(
                    trace_id=trace_id,
                    span_id=span_id,
                    provider=vision_resp.provider,
                    model=vision_resp.model,
                    input_token_count=vision_resp.input_tokens,
                    output_token_count=vision_resp.output_tokens,
                    prompt_summary=f"vision analysis ({len(image_parts)} images)",
                    response_summary=vision_resp.content[:200] if vision_resp.content else "",
                    latency_ms=int((datetime.now(UTC) - call_start).total_seconds() * 1000),
                    stop_reason=vision_resp.stop_reason,
                    error=vision_resp.error,
                )

            if vision_resp.error:
                raise RuntimeError(f"Vision model error: {vision_resp.error}")

            from cogito_agent.models.vision import VisionObservation, _extract_json, _repair_json

            parsed = _extract_json(vision_resp.content)
            if parsed is None:
                parsed = _repair_json(vision_resp.content)
            if parsed is None:
                raise RuntimeError(
                    f"Vision model returned unparseable JSON: {vision_resp.content[:200]}"
                )
            observation = VisionObservation.model_validate(parsed)

            logger.info(
                "Vision pipeline succeeded: %s via %s (%d images)",
                observation.summary[:80],
                vision_resp.model,
                len(image_parts),
            )
            return text_parts, primary_text

        except Exception as exc:
            logger.error("Vision pipeline failed: %s", exc)
            raise RuntimeError(
                f"Vision analysis failed: {exc}. "
                f"Cannot proceed with primary model - images cannot be directly processed."
            ) from exc

    @staticmethod
    def build_vision_messages(
        image_parts: list[ImagePart],
        instruction: str,
    ) -> list[dict[str, object]]:
        """Build legacy dict messages for vision model."""
        from cogito_agent.models.messages import ChatMessage, MessageRole

        vision_prompt = (
            "You are a vision analysis model. Analyze the provided image(s) and "
            "output a structured JSON observation. Do NOT include markdown fences "
            "or extra commentary. Output ONLY valid JSON matching this schema:\n"
            '{"summary": "...", "ocr_text": [...], "objects": [...], '
            '"ui_elements": [...], '
            '"spatial_relations": [...], "uncertainties": [...]}'
        )
        sys_msg = ChatMessage(
            role=MessageRole.system,
            content=[TextPart(text=vision_prompt)],
        )
        user_msg = ChatMessage(
            role=MessageRole.user,
            content=[*image_parts],
        )
        msgs: list[dict[str, object]] = [
            sys_msg.to_legacy_dict(),
            user_msg.to_legacy_dict(),
        ]
        if instruction.strip():
            inst_msg = ChatMessage(
                role=MessageRole.user,
                content=[TextPart(text=instruction)],
            )
            msgs.append(inst_msg.to_legacy_dict())
        return msgs
