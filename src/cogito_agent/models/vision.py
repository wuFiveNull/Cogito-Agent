from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.models.messages import ChatMessage, ImagePart, TextPart

logger = logging.getLogger(__name__)


VISION_SYSTEM_PROMPT = (
    "You are a vision analysis model. Analyze the provided image(s) and "
    "output a structured JSON observation. Do NOT include markdown fences "
    "or extra commentary. Output ONLY valid JSON matching this schema:\n"
    '{"summary": "...", "ocr_text": [...], "objects": [...], '
    '"people": [...], "ui_elements": [...], '
    '"spatial_relations": [...], "uncertainties": [...]}'
)


class VisionObservation(BaseModel):
    summary: str = ""
    ocr_text: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    ui_elements: list[dict[str, object]] = Field(default_factory=list)
    spatial_relations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


_JSON_RE = re.compile(r"\{[^{}]*\}")


def _extract_json(text: str) -> dict[str, Any] | None:
    """Try to extract and parse JSON from model output."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find JSON in markdown code blocks
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try to find any JSON-like structure
    for match in _JSON_RE.finditer(text):
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
    return None


def _repair_json(text: str) -> dict[str, Any] | None:
    """Attempt basic JSON repair for common LLM output issues."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    if cleaned.endswith(","):
        cleaned = cleaned[:-1]
    # Balance braces
    open_count = cleaned.count("{")
    close_count = cleaned.count("}")
    if open_count > close_count:
        cleaned += "}" * (open_count - close_count)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def analyze_image(
    adapter: ModelAdapter,
    image_parts: list[ImagePart],
    instruction: str = "",
    max_repair_attempts: int = 1,
) -> VisionObservation:
    """Send image(s) to a vision model and return a structured observation.

    Args:
        adapter: A ModelAdapter connected to a vision-capable model.
        image_parts: The image content to analyze.
        instruction: Optional additional instruction for the vision model.
        max_repair_attempts: How many times to retry on parse failure.

    Returns:
        A VisionObservation with structured analysis.

    Raises:
        RuntimeError: If the vision model cannot produce valid JSON after
                      all repair attempts.
    """
    messages = [
        ChatMessage(
            role="system",
            content=[TextPart(text=VISION_SYSTEM_PROMPT)],
        ),
        ChatMessage(
            role="user",
            content=[*image_parts],
        ),
    ]
    if instruction:
        messages.append(
            ChatMessage(
                role="user",
                content=[TextPart(text=instruction)],
            )
        )

    legacy_msgs = [m.to_legacy_dict() for m in messages]

    last_error = ""
    for attempt in range(1 + max_repair_attempts):
        try:
            resp: ModelResponse = adapter.chat(legacy_msgs)
            if resp.error:
                last_error = resp.error
                logger.warning(
                    "Vision model attempt %d error: %s", attempt + 1, resp.error
                )
                if attempt < max_repair_attempts:
                    continue
                break

            parsed = _extract_json(resp.content)
            if parsed is None:
                parsed = _repair_json(resp.content)

            if parsed is not None:
                return VisionObservation.model_validate(parsed)

            last_error = f"Failed to parse JSON from model output: {resp.content[:200]}"
            logger.warning("Vision model parse failure (attempt %d): %s", attempt + 1, resp.content[:100])

        except Exception as exc:
            last_error = str(exc)
            logger.warning("Vision model exception (attempt %d): %s", attempt + 1, exc)
            if attempt < max_repair_attempts:
                continue
            break

    raise RuntimeError(
        f"Vision analysis failed after {1 + max_repair_attempts} attempts. "
        f"Last error: {last_error}"
    )


def render_observation_as_text(obs: VisionObservation) -> str:
    """Render a VisionObservation as a structured text block for non-vision models."""
    parts: list[str] = ["[Vision Observation from Vision Worker]"]
    if obs.summary:
        parts.append(f"Summary: {obs.summary}")
    if obs.ocr_text:
        parts.append("OCR Text:")
        for line in obs.ocr_text:
            parts.append(f"  - {line}")
    if obs.objects:
        parts.append(f"Objects detected: {', '.join(obs.objects)}")
    if obs.people:
        parts.append(f"People: {', '.join(obs.people)}")
    if obs.ui_elements:
        parts.append("UI Elements:")
        for el in obs.ui_elements:
            parts.append(f"  - {json.dumps(el, ensure_ascii=False)}")
    if obs.spatial_relations:
        parts.append("Spatial Relations:")
        for rel in obs.spatial_relations:
            parts.append(f"  - {rel}")
    if obs.uncertainties:
        parts.append("Uncertainties:")
        for unc in obs.uncertainties:
            parts.append(f"  - {unc}")
    parts.append("[End Vision Observation]")
    return "\n".join(parts)
