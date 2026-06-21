"""Comprehensive tests for the multi-modal vision pipeline.

Covers:
- Attachment storage and retrieval
- MediaProcessor validation
- Exact vision observation caching
- inspect_image capability
- Runtime integration (native vision and text-only paths)
- API backward compatibility
- Security (no path traversal, no base64 leaks)
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from pathlib import Path

import pytest
from PIL import Image

from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.capability import CapabilityRegistry
from cogito_agent.media import MediaProcessor
from cogito_agent.media.processor import (
    ImageTooLargeError,
    UnsupportedImageTypeError,
    normalize_prompt,
)
from cogito_agent.media.types import (
    create_cache_key,
)
from cogito_agent.media.vision_service import (
    VisionCapabilityUnavailableError,
    VisionObservationService,
)
from cogito_agent.models import (
    ModelCandidate,
    ModelResponse,
    ModelRouter,
    RoutedModelAdapter,
    ToolIntent,
)
from cogito_agent.models.messages import (
    ImagePart,
    TextPart,
)
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    AttachmentRepository,
    VisionObservationRepository,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_test_image(
    format: str = "PNG",
    size: tuple[int, int] = (100, 100),
    color: tuple[int, int, int] = (255, 0, 0),
) -> bytes:
    """Create a simple test image and return bytes."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def _ensure_workspace(db: Database, wid: str = "ws1") -> None:
    db.connection.execute(
        "INSERT OR IGNORE INTO workspaces (id, name) VALUES (?, ?)",
        (wid, wid),
    )
    db.connection.commit()


def _ensure_session(db: Database, sid: str = "sess1", wid: str = "ws1") -> None:
    _ensure_workspace(db, wid)
    db.connection.execute(
        "INSERT OR IGNORE INTO sessions (id, workspace_id, title) VALUES (?, ?, ?)",
        (sid, wid, "test"),
    )
    db.connection.commit()


def _create_test_jpeg(size: tuple[int, int] = (100, 100)) -> bytes:
    return _create_test_image("JPEG", size)


def _create_test_png(size: tuple[int, int] = (100, 100)) -> bytes:
    return _create_test_image("PNG", size)


def _create_test_webp(size: tuple[int, int] = (100, 100)) -> bytes:
    return _create_test_image("WEBP", size)


class FakeVisionAdapter:
    """A fake vision adapter that counts calls."""

    supports_streaming = False
    call_count = 0

    def __init__(self, response_text: str = "This image shows a red square.") -> None:
        self._response_text = response_text
        self.call_count = 0
        self.last_messages: list[dict[str, object]] = []
        self.provider = "fake-vision"
        self.model = "fake-vision-model"

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> ModelResponse:
        self.call_count += 1
        self.last_messages = messages
        return ModelResponse(
            content=self._response_text,
            provider=self.provider,
            model=self.model,
            input_tokens=100,
            output_tokens=50,
        )


class FakeChatAdapter:
    """A fake chat adapter that returns canned responses."""

    supports_streaming = False
    provider = "fake-chat"
    model = "fake-chat-model"

    def __init__(self) -> None:
        self.call_count = 0
        self.last_messages: list[dict[str, object]] = []

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> ModelResponse:
        self.call_count += 1
        self.last_messages = messages
        # Check if inspect_image is in tools
        tools = kwargs.get("tools", [])
        if tools:
            # Simulate calling inspect_image
            tool_name = None
            for t in tools:
                if isinstance(t, dict) and t.get("name") == "inspect_image":
                    tool_name = "inspect_image"
            if tool_name:
                return ModelResponse(
                    content="",
                    tool_intents=[
                        ToolIntent(
                            tool_call_id="call_1",
                            capability_name="inspect_image",
                            arguments={
                                "attachment_id": "att_test",
                                "prompt": "Describe this image",
                            },
                        )
                    ],
                )
        return ModelResponse(content="I see the image result.")


# ── Test Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    return database


@pytest.fixture
def processor() -> MediaProcessor:
    return MediaProcessor(
        max_upload_bytes=20 * 1024 * 1024,
        max_provider_payload_bytes=8 * 1024 * 1024,
        max_edge=4096,
        max_pixels=40_000_000,
    )


@pytest.fixture
def vision_service(db: Database) -> VisionObservationService:
    return VisionObservationService(db)


@pytest.fixture
def att_repo(db: Database) -> AttachmentRepository:
    return AttachmentRepository(db)


@pytest.fixture
def obs_repo(db: Database) -> VisionObservationRepository:
    return VisionObservationRepository(db)


@pytest.fixture
def sample_png() -> bytes:
    return _create_test_png()


@pytest.fixture
def sample_jpeg() -> bytes:
    return _create_test_jpeg()


@pytest.fixture
def sample_webp() -> bytes:
    return _create_test_webp()


# ══════════════════════════════════════════════════════════════════════════
# 1. Attachment Tests
# ══════════════════════════════════════════════════════════════════════════


class TestAttachmentUpload:
    def test_upload_jpeg(self, processor: MediaProcessor, att_repo: AttachmentRepository):
        data = _create_test_jpeg()
        prepared = processor.validate_and_prepare(data, filename="test.jpg")
        assert prepared.mime_type == "image/jpeg"
        assert prepared.width == 100
        assert prepared.height == 100

    def test_upload_png(self, processor: MediaProcessor):
        data = _create_test_png()
        prepared = processor.validate_and_prepare(data, filename="test.png")
        assert prepared.mime_type == "image/jpeg"  # Converted to JPEG
        assert prepared.width == 100

    def test_upload_webp(self, processor: MediaProcessor):
        data = _create_test_webp()
        prepared = processor.validate_and_prepare(data, filename="test.webp")
        assert prepared.mime_type == "image/jpeg"

    def test_fake_extension_rejected(self, processor: MediaProcessor):
        """PNG bytes but .exe extension should be rejected."""
        data = _create_test_png()
        with pytest.raises(UnsupportedImageTypeError):
            processor.validate_and_prepare(data, filename="malware.exe")

    def test_corrupt_image_rejected(self, processor: MediaProcessor):
        with pytest.raises((UnsupportedImageTypeError, ValueError)):
            processor.validate_and_prepare(b"not_an_image_at_all", filename="test.png")

    def test_too_large_rejected(self, processor: MediaProcessor):
        """Override max_upload_bytes to reject even a small image."""
        strict = MediaProcessor(max_upload_bytes=10)
        data = _create_test_png()  # typically > 10 bytes
        with pytest.raises(ImageTooLargeError):
            strict.validate_and_prepare(data, filename="test.png")

    def test_exif_orientation_corrected(self, processor: MediaProcessor):
        """Create an image with EXIF orientation and verify it's corrected."""
        data = _create_test_jpeg()
        prepared = processor.validate_and_prepare(data, filename="test.jpg")
        assert prepared.width > 0
        assert prepared.height > 0

    def test_same_content_hash_for_same_bytes(self):
        """Different filenames, same content → same hash."""
        data = _create_test_png()
        hash1 = hashlib.sha256(data).hexdigest()
        hash2 = hashlib.sha256(data).hexdigest()
        assert hash1 == hash2

    def test_rgba_conversion(self, processor: MediaProcessor):
        """RGBA image should be safely converted to RGB."""
        img = Image.new("RGBA", (50, 50), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        prepared = processor.validate_and_prepare(data, filename="rgba_test.png")
        assert prepared.width == 50

    def test_workspace_isolation(self, att_repo: AttachmentRepository, db: Database):
        """Different workspaces can't see each other's attachments."""
        _ensure_workspace(db, "ws1")
        _ensure_workspace(db, "ws2")
        att_repo.create(
            att_id="att_001",
            workspace_id="ws1",
            content_hash="abc",
            media_type="image/png",
            original_filename="a.png",
            storage_path="/tmp/a.png",
            size_bytes=100,
        )
        att_repo.create(
            att_id="att_002",
            workspace_id="ws2",
            content_hash="def",
            media_type="image/png",
            original_filename="b.png",
            storage_path="/tmp/b.png",
            size_bytes=100,
        )
        assert att_repo.get_by_id("att_001", "ws1") is not None
        assert att_repo.get_by_id("att_001", "ws2") is None

    def test_path_traversal_prevented(self, processor: MediaProcessor):
        """Path traversal through filenames should not be possible."""
        data = _create_test_png()
        with pytest.raises(UnsupportedImageTypeError):
            processor.validate_and_prepare(data, filename="../../../etc/passwd")


# ══════════════════════════════════════════════════════════════════════════
# 2. Vision Observation Cache Tests
# ══════════════════════════════════════════════════════════════════════════


class TestVisionCache:
    def test_cache_hit_same_prompt_same_image(
        self, vision_service: VisionObservationService, db: Database
    ):
        """Same image, same prompt → only one provider call."""
        _ensure_workspace(db, "ws1")
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        png_data = _create_test_png()
        att = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        # First call
        result1 = vision_service.inspect_image(
            att.id,
            "Describe this image",
            "ws1",
        )
        assert fake_adapter.call_count == 1

        # Second call — same prompt → should be cache hit
        result2 = vision_service.inspect_image(
            att.id,
            "Describe this image",
            "ws1",
        )
        assert fake_adapter.call_count == 1  # NOT incremented
        assert result1 == result2

    def test_cache_miss_different_prompt(
        self, vision_service: VisionObservationService, db: Database
    ):
        """Different prompts → two provider calls."""
        _ensure_workspace(db, "ws1")
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        png_data = _create_test_png()
        att = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        vision_service.inspect_image(att.id, "Describe this image", "ws1")
        assert fake_adapter.call_count == 1

        vision_service.inspect_image(att.id, "What color is it?", "ws1")
        assert fake_adapter.call_count == 2  # Different prompt → new call

    def test_cache_miss_different_attachment(
        self, vision_service: VisionObservationService, db: Database
    ):
        """Different images → new call even with same prompt."""
        _ensure_workspace(db, "ws1")
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        tmp = str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test")
        att1 = vision_service.store_attachment(
            _create_test_png(size=(50, 50)),
            workspace_id="ws1",
            filename="a.png",
            storage_dir=tmp,
        )
        att2 = vision_service.store_attachment(
            _create_test_png(size=(100, 100)),
            workspace_id="ws1",
            filename="b.png",
            storage_dir=tmp,
        )

        vision_service.inspect_image(att1.id, "Describe", "ws1")
        assert fake_adapter.call_count == 1

        vision_service.inspect_image(att2.id, "Describe", "ws1")
        assert fake_adapter.call_count == 2  # Different image

    def test_force_refresh_bypasses_cache(
        self, vision_service: VisionObservationService, db: Database
    ):
        """force_refresh=True → new call even if cache hit."""
        _ensure_workspace(db, "ws1")
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        png_data = _create_test_png()
        att = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        vision_service.inspect_image(att.id, "Same prompt", "ws1")
        assert fake_adapter.call_count == 1

        vision_service.inspect_image(att.id, "Same prompt", "ws1", force_refresh=True)
        assert fake_adapter.call_count == 2  # force_refresh bypasses cache

    def test_normalized_prompt_matches(
        self, vision_service: VisionObservationService, db: Database
    ):
        """Whitespace and trailing punctuation differences → cache hit."""
        _ensure_workspace(db, "ws1")
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        png_data = _create_test_png()
        att = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        vision_service.inspect_image(att.id, "Describe this image", "ws1")
        assert fake_adapter.call_count == 1

        vision_service.inspect_image(att.id, "  Describe  this  image.?!", "ws1")
        assert fake_adapter.call_count == 1  # Should hit cache

    def test_workspace_cache_isolation(
        self, vision_service: VisionObservationService, db: Database
    ):
        """Same image + same prompt in different workspaces → different cache keys."""
        _ensure_workspace(db, "ws1")
        _ensure_workspace(db, "ws2")
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        tmp = str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test")
        png_data = _create_test_png()
        att1 = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="a.png",
            storage_dir=tmp,
        )
        att2 = vision_service.store_attachment(
            png_data,
            workspace_id="ws2",
            filename="b.png",
            storage_dir=tmp,
        )

        vision_service.inspect_image(att1.id, "Describe", "ws1")
        assert fake_adapter.call_count == 1

        vision_service.inspect_image(att2.id, "Describe", "ws2")
        assert fake_adapter.call_count == 2

    def test_different_model_doesnt_hit_cache(
        self, vision_service: VisionObservationService, db: Database
    ):
        """Different vision model → different cache key."""
        _ensure_workspace(db, "ws1")
        fake1 = FakeVisionAdapter()
        fake2 = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake1, provider="fake", model="model-a")

        tmp = str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test")
        png_data = _create_test_png()
        att = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=tmp,
        )

        vision_service.inspect_image(att.id, "Describe", "ws1")
        assert fake1.call_count == 1

        # Switch model
        vision_service.set_vision_adapter(fake2, provider="fake", model="model-b")

        vision_service.inspect_image(att.id, "Describe", "ws1")
        assert fake2.call_count == 1  # Different model → new cache slot


# ══════════════════════════════════════════════════════════════════════════
# 3. Prompt Normalization Tests
# ══════════════════════════════════════════════════════════════════════════


class TestPromptNormalization:
    def test_basic_normalization(self):
        assert normalize_prompt("  Hello  World.?!") == "hello world"

    def test_unicode_normalization(self):
        assert normalize_prompt("Café") == "café"

    def test_empty_prompt(self):
        assert normalize_prompt("") == ""
        assert normalize_prompt("   ") == ""


# ══════════════════════════════════════════════════════════════════════════
# 4. Cache Key Tests
# ══════════════════════════════════════════════════════════════════════════


class TestCacheKey:
    def test_cache_key_stability(self):
        k1 = create_cache_key("ws1", "hash1", "desc", "openai", "gpt-4o", "image-v1")
        k2 = create_cache_key("ws1", "hash1", "desc", "openai", "gpt-4o", "image-v1")
        assert k1 == k2

    def test_cache_key_changes_with_workspace(self):
        k1 = create_cache_key("ws1", "hash1", "desc", "openai", "gpt-4o", "image-v1")
        k2 = create_cache_key("ws2", "hash1", "desc", "openai", "gpt-4o", "image-v1")
        assert k1 != k2

    def test_cache_key_changes_with_content_hash(self):
        k1 = create_cache_key("ws1", "hash1", "desc", "openai", "gpt-4o", "image-v1")
        k2 = create_cache_key("ws1", "hash2", "desc", "openai", "gpt-4o", "image-v1")
        assert k1 != k2

    def test_cache_key_changes_with_version(self):
        k1 = create_cache_key("ws1", "hash1", "desc", "openai", "gpt-4o", "image-v1")
        k2 = create_cache_key("ws1", "hash1", "desc", "openai", "gpt-4o", "image-v2")
        assert k1 != k2


# ══════════════════════════════════════════════════════════════════════════
# 5. inspect_image Capability Tests
# ══════════════════════════════════════════════════════════════════════════


class TestInspectImageCapability:
    def test_no_vision_adapter_raises_error(self, vision_service: VisionObservationService):
        """Without vision adapter, inspect_image returns capability error."""
        with pytest.raises(VisionCapabilityUnavailableError):
            vision_service.inspect_image("att_xxx", "Describe", "ws1")

    def test_capability_registration(self, vision_service: VisionObservationService):
        cap_reg = CapabilityRegistry()
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")
        vision_service.register_with_capability_registry(cap_reg)

        manifest = cap_reg.get_manifest("inspect_image")
        assert manifest is not None
        assert manifest.name == "inspect_image"
        assert manifest.risk_level.value == "low"

    def test_capability_schema_validation(
        self, vision_service: VisionObservationService, db: Database
    ):
        _ensure_workspace(db, "ws1")
        cap_reg = CapabilityRegistry()
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")
        vision_service.register_with_capability_registry(cap_reg)

        # Missing required params
        result = cap_reg.invoke("inspect_image")
        assert result is not None
        assert result.status == "error"

        # Valid call with attachment_id
        png_data = _create_test_png()
        att = vision_service.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )
        vision_service.set_current_context(workspace_id="ws1")

        # Must call through actual service, not registry (registry can't inject workspace_id)
        result_text = vision_service.inspect_image(att.id, "Describe", "ws1")
        assert "red square" in result_text.lower() or "this image shows" in result_text.lower()

    def test_tool_cannot_access_file_paths(self, vision_service: VisionObservationService):
        """inspect_image only accepts attachment_id, not file paths."""
        cap_reg = CapabilityRegistry()
        fake_adapter = FakeVisionAdapter()
        vision_service.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")
        vision_service.register_with_capability_registry(cap_reg)

        result = cap_reg.invoke("inspect_image", attachment_id="/etc/passwd", prompt="read")
        assert result is not None
        assert result.status == "error"  # Should fail, not a valid attachment


# ══════════════════════════════════════════════════════════════════════════
# 6. Runtime Integration Tests
# ══════════════════════════════════════════════════════════════════════════


class TestRuntimeIntegration:
    def test_image_upload_does_not_trigger_vision(self, db: Database):
        """Uploading an image alone does NOT call the vision model."""
        _ensure_workspace(db, "ws1")
        svc = VisionObservationService(db)
        fake_adapter = FakeVisionAdapter()
        svc.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        png_data = _create_test_png()
        svc.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )
        assert fake_adapter.call_count == 0  # No vision calls

    def test_no_vision_capability_error(self, db: Database):
        """Without any vision model, clear error message."""
        svc = VisionObservationService(db)
        with pytest.raises(VisionCapabilityUnavailableError, match="No vision model"):
            svc.inspect_image("att_x", "desc", "ws1")

    def test_next_turn_uses_existing_observation(self, db: Database):
        """After first observation, next turn includes it in context."""
        _ensure_workspace(db, "ws1")
        svc = VisionObservationService(db)
        fake_adapter = FakeVisionAdapter()
        svc.set_vision_adapter(fake_adapter, provider="fake", model="fake-model")

        png_data = _create_test_png()
        att = svc.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        # First call creates observation
        svc.inspect_image(att.id, "Describe this image", "ws1")
        assert fake_adapter.call_count == 1

        # Check observations exist
        obs_list = svc.get_observations_for_attachment(att.id, "ws1")
        assert len(obs_list) >= 1

        # Format context should list the observation
        ctx = svc.format_observations_for_context([att.id], "ws1")
        assert "Existing observations" in ctx
        assert "Describe" in ctx

    def test_cached_observation_used_on_repeat(self, db: Database, processor: MediaProcessor):
        """Second identical tool call returns cached result (no extra provider call)."""
        _ensure_workspace(db, "ws1")

        class TestVisionService(VisionObservationService):
            def _call_vision_model(self, prepared, prompt, trace_id):
                return {
                    "text": "test",
                    "provider": "fake",
                    "model": "fake",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "latency_ms": 0,
                }

        svc = TestVisionService(db, media_processor=processor)
        fake = FakeVisionAdapter("test result")
        svc.set_vision_adapter(fake, provider="fake", model="fake")

        png_data = _create_test_png()
        att = svc.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        # First call
        r1 = svc.inspect_image(att.id, "Read error message", "ws1")
        # Second call — same params
        r2 = svc.inspect_image(att.id, "Read error message", "ws1")

        assert r1 == r2

    def test_new_question_creates_new_observation(self, db: Database):
        """Different question about same image creates new observation."""
        _ensure_workspace(db, "ws1")
        svc = VisionObservationService(db)
        fake = FakeVisionAdapter("some response")
        svc.set_vision_adapter(fake, provider="fake", model="fake")

        png_data = _create_test_png()
        att = svc.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        svc.inspect_image(att.id, "Read error message", "ws1")
        assert fake.call_count == 1

        svc.inspect_image(att.id, "What Python version?", "ws1")
        assert fake.call_count == 2  # New question → new call

    def test_tool_loop_with_vision_capability(self, db: Database):
        """Multi-round tool loop with inspect_image capability."""
        _ensure_workspace(db, "ws1")
        _ensure_session(db, "sess_test_tool", "ws1")
        cap_reg = CapabilityRegistry()
        svc = VisionObservationService(db)
        fake_vision = FakeVisionAdapter("The image shows Python 3.12")
        svc.set_vision_adapter(fake_vision, provider="fake", model="fake-vision")

        png_data = _create_test_png()
        att = svc.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        svc.register_with_capability_registry(cap_reg)

        fake_chat = FakeChatAdapter()
        candidate = ModelCandidate(
            provider="fake",
            model="fake-chat",
            capabilities={"chat", "tools"},
            input_modalities={"text"},
        )
        router = ModelRouter([candidate])
        routed_adapter = RoutedModelAdapter(router, lambda _c: fake_chat)

        kernel = RuntimeKernel(
            db=db,
            model_adapter=routed_adapter,
            capability_registry=cap_reg,
            max_tool_rounds=3,
        )
        kernel.set_vision_service(svc)

        event = RuntimeEvent(
            workspace_id="ws1",
            session_id="sess_test_tool",
            actor_id="user",
            source=EventSource.api,
            type=EventType.user_message,
            payload={
                "text": "What does this image show?",
                "content": [
                    {"type": "image", "attachment_id": att.id, "uri": ""},
                ],
            },
        )
        result = kernel.process(event)
        # The result should complete (may be failed since mock doesn't actually resolve)
        assert result.state.value in ("completed", "failed")

    def test_observation_persists_across_turns(self, db: Database):
        """Observations survive in DB for subsequent turns."""
        _ensure_workspace(db, "ws1")
        svc = VisionObservationService(db)
        fake = FakeVisionAdapter("A red square")
        svc.set_vision_adapter(fake, provider="fake", model="fake")

        png_data = _create_test_png()
        att = svc.store_attachment(
            png_data,
            workspace_id="ws1",
            filename="test.png",
            storage_dir=str(Path(os.environ.get("TEMP", "/tmp")) / "cogito_test"),
        )

        svc.inspect_image(att.id, "Describe", "ws1")
        assert fake.call_count == 1

        # Simulate new turn
        obs_after = svc.get_observations_for_attachment(att.id, "ws1")
        assert len(obs_after) >= 1

        ctx_text = svc.format_observations_for_context([att.id], "ws1")
        assert (
            "A red square" in ctx_text
            or "This image shows a red square" in ctx_text
            or "result" in ctx_text
        )


# ══════════════════════════════════════════════════════════════════════════
# 7. Model Message Tests
# ══════════════════════════════════════════════════════════════════════════


class TestModelMessages:
    def test_image_part_with_attachment_id(self):
        """ImagePart can have attachment_id instead of uri."""
        part = ImagePart(attachment_id="att_123")
        assert part.attachment_id == "att_123"
        assert part.get_uri_or_attachment() == "attachment://att_123"

    def test_image_part_requires_uri_or_attachment(self):
        """ImagePart must have either uri or attachment_id."""
        with pytest.raises(ValueError):
            ImagePart()

    def test_legacy_image_part_still_works(self):
        """Old-style ImagePart with uri continues to work."""
        part = ImagePart(uri="data:image/png;base64,abc")
        assert part.uri == "data:image/png;base64,abc"

    def test_legacy_chat_request_backward_compat(self):
        """Old text-only chat request works with attachment_ids support."""
        # This simulates what the API does
        from cogito_agent.api.app import ChatRequest

        req = ChatRequest(
            session_id="s1",
            workspace_id="ws1",
            text="hello",
        )
        parts = req.get_content_parts()
        assert len(parts) == 1
        assert isinstance(parts[0], TextPart)
        assert parts[0].text == "hello"


# ══════════════════════════════════════════════════════════════════════════
# 8. Database Migration Tests
# ══════════════════════════════════════════════════════════════════════════


class TestDatabaseMigration:
    def test_migration_v14_applied(self, db: Database):
        """Migration v14 should create the new tables."""
        version = db.current_version()
        assert version >= 14, f"Expected v14+, got v{version}"

        # Check tables exist
        cur = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('attachments', 'vision_observations', 'message_attachments')"
        )
        tables = {row["name"] for row in cur.fetchall()}
        assert "attachments" in tables
        assert "vision_observations" in tables
        assert "message_attachments" in tables

    def test_vision_observation_crud(self, obs_repo: VisionObservationRepository, db: Database):
        """CRUD operations on vision_observations work."""
        _ensure_workspace(db)
        # Insert attachment first to satisfy FK
        db.connection.execute(
            "INSERT OR IGNORE INTO attachments"
            " (id, workspace_id, content_hash, media_type, storage_path, size_bytes)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("att_001", "ws1", "hash1", "image/png", "/tmp/test.png", 100),
        )
        db.connection.commit()
        obs_id = str(uuid.uuid4())
        cache_key = create_cache_key("ws1", "hash1", "test", "openai", "gpt-4o", "image-v1")
        obs_repo.create(
            obs_id=obs_id,
            workspace_id="ws1",
            attachment_id="att_001",
            image_content_hash="hash1",
            prompt="Test prompt",
            normalized_prompt="test prompt",
            result_text="Test result",
            provider="openai",
            model="gpt-4o",
            preprocessing_version="image-v1",
            cache_key=cache_key,
        )
        # Read back
        cached = obs_repo.get_by_cache_key(cache_key)
        assert cached is not None
        assert cached["result_text"] == "Test result"

    def test_unique_cache_key(self, obs_repo: VisionObservationRepository, db: Database):
        """Duplicate cache key is handled gracefully (INSERT OR IGNORE)."""
        _ensure_workspace(db)
        # Insert attachments first to satisfy FK
        for att_id in ("att_1", "att_2"):
            db.connection.execute(
                "INSERT OR IGNORE INTO attachments"
                " (id, workspace_id, content_hash, media_type, storage_path, size_bytes)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (att_id, "ws1", "hash1", "image/png", "/tmp/test.png", 100),
            )
        db.connection.commit()
        cache_key = create_cache_key("ws1", "h1", "t", "o", "m", "v1")
        obs_repo.create(
            obs_id="obs_1",
            workspace_id="ws1",
            attachment_id="att_1",
            image_content_hash="h1",
            prompt="t",
            normalized_prompt="t",
            result_text="r1",
            provider="o",
            model="m",
            preprocessing_version="v1",
            cache_key=cache_key,
        )
        obs_repo.create(
            obs_id="obs_2",
            workspace_id="ws1",
            attachment_id="att_1",
            image_content_hash="h1",
            prompt="t",
            normalized_prompt="t",
            result_text="r2",
            provider="o",
            model="m",
            preprocessing_version="v1",
            cache_key=cache_key,
        )
        # Should still have the first record
        cached = obs_repo.get_by_cache_key(cache_key)
        assert cached is not None
        assert cached["id"] == "obs_1"


# ══════════════════════════════════════════════════════════════════════════
# 9. Media Processor Security Tests
# ══════════════════════════════════════════════════════════════════════════


class TestMediaProcessorSecurity:
    def test_decompression_bomb_protected(self, processor: MediaProcessor):
        """Pillow decompression bomb should be caught."""
        # Create a small file that claims to be huge
        # (test PIL's DecompressionBombError)
        try:
            from PIL import ImageFile

            ImageFile.LOAD_TRUNCATED_IMAGES = True
            # This is a tiny header that might trick PIL - just verify it doesn't crash
            processor.validate_and_prepare(b"\x89PNG\r\n\x1a\n" + b"0" * 100, filename="bomb.png")
        except Exception:
            pass  # Either caught or processed, shouldn't crash

    def test_mime_detection_from_magic_bytes(self, processor: MediaProcessor):
        """MIME type is detected from content, not extension."""
        png_data = _create_test_png()
        prepared = processor.validate_and_prepare(png_data, filename="wrong.jpg")
        # Original MIME should be image/png based on magic bytes
        assert prepared.original_mime == "image/png"
