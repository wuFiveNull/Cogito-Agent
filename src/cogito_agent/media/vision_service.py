from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.capability.tools import INSPECT_IMAGE_MANIFEST
from cogito_agent.media.processor import (
    MEDIA_PREPROCESSING_VERSION,
    MediaProcessor,
    PreparedImage,
    normalize_prompt,
)
from cogito_agent.media.types import (
    Attachment,
    create_attachment_id,
    create_cache_key,
)
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    AttachmentRepository,
    VisionObservationRepository,
)

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = (
    "You are a vision analysis model. Analyze the provided image and "
    "answer the user's question about it. Be specific and concise. "
    "Output ONLY the analysis results as plain text, no markdown fences."
)


def _opt_int(val: object) -> int | None:
    if val is None:
        return None
    return int(str(val))


class VisionCapabilityUnavailableError(RuntimeError):
    pass


class AttachmentNotFoundError(ValueError):
    pass


class AttachmentAccessDeniedError(ValueError):
    pass


class VisionObservationService:
    """Coordinates image attachment storage, preprocessing, and vision model calls.

    This service is the core of the multi-modal vision pipeline:
    1. Stores uploaded images as Attachments
    2. Preprocesses images through MediaProcessor
    3. Checks exact cache before calling vision model
    4. Calls vision model (if needed) and persists observation
    5. Provides methods to retrieve observations for context building
    """

    def __init__(
        self,
        db: Database,
        media_processor: MediaProcessor | None = None,
    ) -> None:
        self._db = db
        self._att_repo = AttachmentRepository(db)
        self._obs_repo = VisionObservationRepository(db)
        self._processor = media_processor or MediaProcessor()
        self._vision_adapter: Any = None
        self._vision_provider: str = ""
        self._vision_model: str = ""
        self._tracer: Any = None
        self._current_workspace_id: str = ""
        self._current_trace_id: str = ""

    def register_with_capability_registry(self, cap_reg: CapabilityRegistry) -> None:
        """Register the inspect_image capability with the capability registry."""

        def _inspect_image_fn(
            attachment_id: str = "",
            prompt: str = "",
            force_refresh: bool = False,
        ) -> ToolResult:
            if not attachment_id:
                return ToolResult(
                    status="error",
                    summary="attachment_id is required",
                    error="Missing attachment_id argument",
                )
            if not prompt:
                return ToolResult(
                    status="error",
                    summary="prompt is required",
                    error="Missing prompt argument",
                )
            try:
                result = self.inspect_image(
                    attachment_id=attachment_id,
                    prompt=prompt,
                    workspace_id=self._current_workspace_id,
                    force_refresh=force_refresh,
                    trace_id=self._current_trace_id,
                )
                return ToolResult(
                    status="ok",
                    summary=result[:200] if result else "",
                    data={"result": result},
                )
            except AttachmentNotFoundError as e:
                return ToolResult(status="error", summary=str(e), error=str(e))
            except AttachmentAccessDeniedError as e:
                return ToolResult(status="error", summary=str(e), error=str(e))
            except VisionCapabilityUnavailableError as e:
                return ToolResult(status="error", summary=str(e), error=str(e))
            except Exception as e:
                return ToolResult(status="error", summary=str(e), error=str(e))

        cap_reg.register(INSPECT_IMAGE_MANIFEST.name, INSPECT_IMAGE_MANIFEST, _inspect_image_fn)

    def set_vision_adapter(self, adapter: Any, provider: str = "", model: str = "") -> None:
        self._vision_adapter = adapter
        self._vision_provider = provider
        self._vision_model = model

    def set_tracer(self, tracer: Any) -> None:
        self._tracer = tracer

    def set_current_context(
        self,
        workspace_id: str = "",
        trace_id: str = "",
    ) -> None:
        self._current_workspace_id = workspace_id
        self._current_trace_id = trace_id

    @property
    def has_vision_capability(self) -> bool:
        return self._vision_adapter is not None

    # ── Attachment Storage ─────────────────────────────────────────────────

    def store_attachment(
        self,
        data: bytes,
        workspace_id: str,
        filename: str = "",
        session_id: str | None = None,
        storage_dir: str = "",
    ) -> Attachment:
        """Store uploaded image as an attachment.

        Validates the image, computes SHA-256, saves to disk,
        and persists the record.
        """
        import hashlib
        from pathlib import Path

        content_hash = hashlib.sha256(data).hexdigest()
        media_processor = self._processor
        prepared = media_processor.validate_and_prepare(data, filename=filename)
        att_id = create_attachment_id()

        storage_path = ""
        if storage_dir:
            ws_dir = Path(storage_dir) / workspace_id
            ws_dir.mkdir(parents=True, exist_ok=True)
            file_path = ws_dir / f"{att_id}.jpg"
            file_path.write_bytes(prepared.data)
            storage_path = str(file_path)

        self._att_repo.create(
            att_id=att_id,
            workspace_id=workspace_id,
            content_hash=content_hash,
            media_type=prepared.original_mime,
            original_filename=filename or "unknown",
            storage_path=storage_path,
            size_bytes=len(data),
            width=prepared.width,
            height=prepared.height,
            session_id=session_id,
        )

        return Attachment(
            id=att_id,
            workspace_id=workspace_id,
            session_id=session_id,
            content_hash=content_hash,
            media_type=prepared.original_mime,
            original_filename=filename or "unknown",
            storage_path=storage_path,
            size_bytes=len(data),
            width=prepared.width,
            height=prepared.height,
            created_at=datetime.now(UTC),
        )

    def get_attachment(self, attachment_id: str, workspace_id: str) -> Attachment | None:
        record = self._att_repo.get_by_id(attachment_id, workspace_id)
        if record is None:
            return None
        size_bytes_val: object = record.get("size_bytes", 0)
        return Attachment(
            id=str(record["id"]),
            workspace_id=str(record["workspace_id"]),
            session_id=str(record["session_id"]) if record.get("session_id") else None,
            content_hash=str(record["content_hash"]),
            media_type=str(record["media_type"]),
            original_filename=str(record["original_filename"]),
            storage_path=str(record["storage_path"]),
            size_bytes=int(str(size_bytes_val)),
            width=_opt_int(record.get("width")),
            height=_opt_int(record.get("height")),
            created_at=datetime.fromisoformat(str(record["created_at"])),
        )

    def require_attachment(
        self, attachment_id: str, workspace_id: str, session_id: str | None = None
    ) -> Attachment:
        att = self.get_attachment(attachment_id, workspace_id)
        if att is None:
            raise AttachmentNotFoundError(
                f"Attachment '{attachment_id}' not found in workspace '{workspace_id}'"
            )
        if session_id and att.session_id and att.session_id != session_id:
            raise AttachmentAccessDeniedError(
                f"Attachment '{attachment_id}' does not belong to session '{session_id}'"
            )
        return att

    def read_attachment_bytes(self, attachment: Attachment) -> bytes:
        """Read attachment file bytes from storage."""
        if not attachment.storage_path:
            raise FileNotFoundError(f"No storage path for attachment {attachment.id}")
        from pathlib import Path

        return Path(attachment.storage_path).read_bytes()

    # ── Vision Observation ─────────────────────────────────────────────────

    def inspect_image(
        self,
        attachment_id: str,
        prompt: str,
        workspace_id: str,
        session_id: str | None = None,
        force_refresh: bool = False,
        trace_id: str = "",
    ) -> str:
        """Inspect an image using the vision model, with exact caching.

        Args:
            attachment_id: ID of the stored attachment.
            prompt: The visual question/instruction.
            workspace_id: Current workspace.
            session_id: Optional session scope.
            force_refresh: If True, bypass cache and force new observation.
            trace_id: Current trace for audit.

        Returns:
            Observation result text.

        Raises:
            VisionCapabilityUnavailableError: No vision adapter configured.
            AttachmentNotFoundError: Attachment not found.
        """
        if not self.has_vision_capability:
            raise VisionCapabilityUnavailableError(
                "No vision model is configured. "
                "Set model.vision.enabled=true and configure a vision provider."
            )

        att = self.require_attachment(attachment_id, workspace_id, session_id)
        normalized = normalize_prompt(prompt)

        cache_key = create_cache_key(
            workspace_id=workspace_id,
            image_content_hash=att.content_hash,
            normalized_prompt=normalized,
            vision_provider=self._vision_provider,
            vision_model=self._vision_model,
            preprocessing_version=MEDIA_PREPROCESSING_VERSION,
        )

        # Check cache
        if not force_refresh:
            cached = self._obs_repo.get_by_cache_key(cache_key)
            if cached is not None:
                logger.info(
                    "Vision cache HIT for attachment %s (prompt: %.50s)",
                    attachment_id,
                    prompt,
                )
                self._log_cache_hit(trace_id, attachment_id, cache_key)
                return str(cached["result_text"])

        # Cache miss — call vision model
        logger.info(
            "Vision cache MISS for attachment %s (prompt: %.50s)",
            attachment_id,
            prompt,
        )
        self._log_cache_miss(trace_id, attachment_id, cache_key)

        prepared = self._processor.validate_and_prepare(
            self.read_attachment_bytes(att),
            filename=att.original_filename,
        )

        result = self._call_vision_model(prepared, prompt, trace_id)

        obs_id = str(uuid.uuid4())
        self._obs_repo.create(
            obs_id=obs_id,
            workspace_id=workspace_id,
            session_id=session_id,
            attachment_id=attachment_id,
            image_content_hash=att.content_hash,
            prompt=prompt,
            normalized_prompt=normalized,
            result_text=result["text"],
            provider=result.get("provider", self._vision_provider),
            model=result.get("model", self._vision_model),
            preprocessing_version=MEDIA_PREPROCESSING_VERSION,
            cache_key=cache_key,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            latency_ms=result.get("latency_ms", 0),
            trace_id=trace_id,
        )

        self._log_observation_persist(trace_id, obs_id, cache_key)

        return str(result.get("text", ""))

    def _call_vision_model(
        self, prepared: PreparedImage, prompt: str, trace_id: str
    ) -> dict[str, Any]:
        """Call the vision model adapter."""
        if self._vision_adapter is None:
            raise RuntimeError("Vision adapter not configured")

        data_uri = self._processor.to_data_uri(prepared)
        from cogito_agent.models.messages import ChatMessage, ImagePart, MessageRole, TextPart

        messages = [
            ChatMessage(
                role=MessageRole.system,
                content=[TextPart(text=VISION_SYSTEM_PROMPT)],
            ).to_legacy_dict(),
            ChatMessage(
                role=MessageRole.user,
                content=[
                    ImagePart(uri=data_uri, mime_type=prepared.mime_type),
                    TextPart(text=prompt),
                ],
            ).to_legacy_dict(),
        ]

        from datetime import UTC, datetime

        start = datetime.now(UTC)
        try:
            response = self._vision_adapter.chat(messages)
            latency = int((datetime.now(UTC) - start).total_seconds() * 1000)

            if response.error:
                raise RuntimeError(f"Vision model error: {response.error}")

            return {
                "text": response.content or "",
                "provider": response.provider or self._vision_provider,
                "model": response.model or self._vision_model,
                "input_tokens": response.input_tokens or 0,
                "output_tokens": response.output_tokens or 0,
                "latency_ms": latency,
            }
        except Exception as e:
            logger.error("Vision model call failed: %s", e)
            raise

    def get_observations_for_attachment(
        self, attachment_id: str, workspace_id: str, limit: int = 5
    ) -> list[dict[str, object]]:
        """Get existing observations for an attachment (for context injection)."""
        return self._obs_repo.get_by_attachment(attachment_id, workspace_id, limit=limit)

    def format_observations_for_context(
        self,
        attachment_ids: list[str],
        workspace_id: str,
        max_obs: int = 3,
    ) -> str:
        """Format attachment observations for injection into model context.

        Returns a compact text block listing available observations.
        """
        lines: list[str] = ["[Available image attachments]"]
        for att_id in attachment_ids:
            att = self._att_repo.get_by_id(att_id, workspace_id)
            if att is None:
                continue
            lines.append("")
            lines.append(f"Attachment: {att_id}")
            lines.append(f"Type: {att.get('media_type', 'unknown')}")
            w = att.get("width")
            h = att.get("height")
            if w and h:
                lines.append(f"Dimensions: {w}x{h}")

            observations = self._obs_repo.get_by_attachment(att_id, workspace_id, limit=max_obs)
            if observations:
                lines.append("Existing observations:")
                for i, obs in enumerate(observations, 1):
                    prompt_preview = str(obs.get("prompt", ""))[:80]
                    result_preview = str(obs.get("result_text", ""))[:120]
                    lines.append(f"  {i}. Question: {prompt_preview}")
                    lines.append(f"     Result: {result_preview}")
            else:
                lines.append("  No observations yet — use inspect_image to analyze.")

        lines.append("")
        lines.append(
            "Use existing observations whenever they are sufficient. "
            "Do not call inspect_image merely to repeat an existing observation. "
            "Call inspect_image only when the current task requires visual details "
            "not covered above. Use a narrow, task-specific prompt."
        )
        return "\n".join(lines)

    # ── Trace helpers ──────────────────────────────────────────────────────

    def _log_cache_hit(self, trace_id: str, attachment_id: str, cache_key: str) -> None:
        if self._tracer is None or not trace_id:
            return
        span = self._tracer.create_span(trace_id, "vision.cache_hit", None)
        if span:
            span.input_summary = f"attachment_id={attachment_id}"
            span.output_summary = "cache_key=" + cache_key[:16]
            self._tracer.end_span(span)

    def _log_cache_miss(self, trace_id: str, attachment_id: str, cache_key: str) -> None:
        if self._tracer is None or not trace_id:
            return
        span = self._tracer.create_span(trace_id, "vision.cache_miss", None)
        if span:
            span.input_summary = f"attachment_id={attachment_id}"
            span.output_summary = "cache_key=" + cache_key[:16]
            self._tracer.end_span(span)

    def _log_observation_persist(self, trace_id: str, obs_id: str, cache_key: str) -> None:
        if self._tracer is None or not trace_id:
            return
        span = self._tracer.create_span(trace_id, "vision.observation_persist", None)
        if span:
            span.input_summary = f"obs_id={obs_id}"
            span.output_summary = "cache_key=" + cache_key[:16]
            self._tracer.end_span(span)
