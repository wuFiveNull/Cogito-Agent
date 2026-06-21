from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from pydantic import BaseModel

from cogito_agent.models import ModelAdapter, ModelRouteRequest
from cogito_agent.models.messages import (
    ChatMessage,
    ContentPart,
    ImagePart,
    MessageRole,
    TextPart,
    has_image,
)
from cogito_agent.models.vision import VisionObservation, analyze_image

logger = logging.getLogger(__name__)


class PreparedPrimaryInput(BaseModel):
    messages: list[ChatMessage] = []
    vision_observation: VisionObservation | None = None
    vision_error: str | None = None
    vision_candidate_id: str | None = None
    image_count: int = 0
    attempted_candidates: list[str] = []


class MultimodalCoordinator:
    """Orchestrates the two-phase vision→primary model execution pipeline.

    Phase 1: Detect images → route to Vision Worker → produce VisionObservation.
    Phase 2: Remove images from primary input → inject observation as tool message.
    """

    def __init__(
        self,
        adapter_resolver: Callable[[str], ModelAdapter | None],
        route_fn: Callable[[ModelRouteRequest], str | None],
        vision_candidate_ids: tuple[str, ...] = (),
        backup_vision_candidate_ids: tuple[str, ...] = (),
    ) -> None:
        self._adapter_resolver = adapter_resolver
        self._route_fn = route_fn
        self._vision_candidate_ids = vision_candidate_ids
        self._backup_vision_candidate_ids = backup_vision_candidate_ids

    def prepare_for_primary_model(
        self,
        content: list[ContentPart],
        user_instruction: str = "",
    ) -> PreparedPrimaryInput:
        """Inspect content, run vision if images present, return prepared primary input.

        Args:
            content: The normalized content parts from the user message.
            user_instruction: Original user text instruction.

        Returns:
            PreparedPrimaryInput with modified messages for the primary model.
            If no images, messages contains the unchanged content as a user message.
            If images, images are replaced with VisionObservation as tool message.
        """
        if not has_image(content):
            return PreparedPrimaryInput(
                messages=[
                    ChatMessage(
                        role=MessageRole.user,
                        content=content or [TextPart(text=user_instruction)],
                    )
                ],
                image_count=0,
            )

        image_parts = [p for p in content if isinstance(p, ImagePart)]
        text_parts = [p for p in content if not isinstance(p, ImagePart)]

        primary_text = extract_text(text_parts) or user_instruction  # type: ignore[arg-type]

        vision_call_id = f"vision_{uuid.uuid4().hex[:12]}"
        attempted: list[str] = []
        observation: VisionObservation | None = None
        last_error: str | None = None

        candidate_pool = list(self._vision_candidate_ids) + list(self._backup_vision_candidate_ids)

        for cid in candidate_pool:
            attempted.append(cid)
            adapter = self._adapter_resolver(cid)
            if adapter is None:
                logger.warning("Vision candidate %s: no adapter found", cid)
                last_error = f"no adapter for {cid}"
                continue
            try:
                observation = analyze_image(
                    adapter=adapter,
                    image_parts=image_parts,
                    instruction=primary_text,
                )
                logger.info(
                    "Vision succeeded via %s: %s",
                    cid,
                    observation.summary[:100],
                )
                break
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Vision candidate %s failed: %s", cid, exc)
                continue

        if observation is None:
            return PreparedPrimaryInput(
                messages=[],
                vision_error=(
                    f"All vision candidates failed. "
                    f"Attempted: {', '.join(attempted)}. "
                    f"Last error: {last_error}"
                ),
                image_count=len(image_parts),
                attempted_candidates=attempted,
            )

        obs_json = observation.model_dump_json()

        primary_messages: list[ChatMessage] = [
            ChatMessage(
                role=MessageRole.user,
                content=[TextPart(text=primary_text)],
            ),
            ChatMessage(
                role=MessageRole.tool,
                name="vision.observe",
                tool_call_id=vision_call_id,
                content=[TextPart(text=obs_json)],
            ),
        ]

        log_image_count = len(image_parts)
        return PreparedPrimaryInput(
            messages=primary_messages,
            vision_observation=observation,
            image_count=log_image_count,
            vision_candidate_id=cid if observation else None,
            attempted_candidates=attempted,
        )


def extract_text(parts: list[ContentPart]) -> str:
    """Extract text from a list of content parts (non-image only)."""
    texts: list[str] = []
    for p in parts:
        if isinstance(p, TextPart):
            texts.append(p.text)
    return " ".join(texts).strip()
