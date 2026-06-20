"""Comprehensive tests for the MemeAsset system.

Ensures strict separation: sending memes NEVER calls VLM.
Only analyze_meme / inspect_image may call VLM.
"""

from __future__ import annotations

import io
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.tools import (
    ANALYZE_MEME_MANIFEST,
    REGISTER_MEME_MANIFEST,
    SEARCH_MEMES_MANIFEST,
    SEND_MEME_MANIFEST,
)
from cogito_agent.media import MediaProcessor, MemeAsset, MemeService
from cogito_agent.media.meme_service import MemeAnalysisError, MemeDisabledError, MemeNotFoundError
from cogito_agent.media.types import create_meme_id
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import AttachmentRepository, MemeAssetRepository


# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_test_image(
    format: str = "PNG",
    size: tuple[int, int] = (100, 100),
    color: tuple[int, int, int] = (255, 0, 0),
) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def _ensure_workspace(db: Database, wid: str = "ws1") -> None:
    db.connection.execute(
        "INSERT OR IGNORE INTO workspaces (id, name) VALUES (?, ?)", (wid, wid),
    )
    db.connection.commit()


def _store_attachment(db: Database, data: bytes, ws: str = "ws1") -> str:
    import hashlib
    _ensure_workspace(db, ws)
    content_hash = hashlib.sha256(data).hexdigest()
    att_id = f"att_{uuid.uuid4().hex[:24]}"
    db.connection.execute(
        "INSERT INTO attachments (id, workspace_id, content_hash, media_type, original_filename, storage_path, size_bytes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (att_id, ws, content_hash, "image/png", "meme.png", f"/tmp/{att_id}.jpg", len(data)),
    )
    db.connection.commit()
    return att_id


class FakeVisionAdapter:
    call_count = 0
    response_text: str = ""

    def __init__(self, response_text: str = "") -> None:
        self.call_count = 0
        self.response_text = response_text

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> Any:
        self.call_count += 1
        from cogito_agent.models import ModelResponse
        return ModelResponse(
            content=self.response_text or '{"name":"Test Meme","description":"A test meme","emotions":["happy"],"use_cases":["testing"]}',
            provider="fake-vision", model="fake-vision-model",
            input_tokens=50, output_tokens=20,
        )


class FakeVisionService:
    def __init__(self, adapter: FakeVisionAdapter | None = None) -> None:
        self._adapter = adapter or FakeVisionAdapter()
        self.call_count: int = 0

    @property
    def has_vision_capability(self) -> bool:
        return True

    def set_vision_adapter(self, adapter: Any, **kwargs: str) -> None:
        pass

    def inspect_image(
        self, attachment_id: str, prompt: str, workspace_id: str, **kwargs: object
    ) -> str:
        self.call_count += 1
        self._adapter.call_count += 1
        return self._adapter.response_text or (
            '{"name":"VLM Meme","description":"VLM analysis","emotions":["cool"],"use_cases":["demo"]}'
        )


class FakeChannel:
    send_image_call_count = 0
    last_image_bytes: bytes | None = None
    last_media_type: str = ""
    last_caption: str = ""


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    return database


@pytest.fixture
def meme_repo(db: Database) -> MemeAssetRepository:
    return MemeAssetRepository(db)


@pytest.fixture
def att_repo(db: Database) -> AttachmentRepository:
    return AttachmentRepository(db)


@pytest.fixture
def processor() -> MediaProcessor:
    return MediaProcessor()


@pytest.fixture
def meme_svc(db: Database) -> MemeService:
    return MemeService(db)


@pytest.fixture
def sample_png() -> bytes:
    return _create_test_image()


@pytest.fixture
def sample_att_id(db: Database, sample_png: bytes) -> str:
    return _store_attachment(db, sample_png)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Database Migration
# ═══════════════════════════════════════════════════════════════════════════


class TestDatabaseMigration:
    def test_migration_v15_applied(self, db: Database):
        version = db.current_version()
        assert version >= 15, f"Expected v15+, got v{version}"
        cur = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meme_assets'"
        )
        assert cur.fetchone() is not None


# ═══════════════════════════════════════════════════════════════════════════
# 2. MemeAssetRepository
# ═══════════════════════════════════════════════════════════════════════════


class TestMemeAssetRepository:
    def test_create_and_get(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_id = create_meme_id()
        meme_repo.create(
            meme_id=meme_id, workspace_id="ws1", attachment_id=att_id,
            content_hash="abc123", name="Doge", description="Wow",
        )
        record = meme_repo.get(meme_id, "ws1")
        assert record is not None
        assert record["name"] == "Doge"

    def test_get_by_attachment_id(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_repo.create(
            meme_id=create_meme_id(), workspace_id="ws1", attachment_id=att_id,
            content_hash="abc", name="Test", description="test",
        )
        found = meme_repo.get_by_attachment_id(att_id, "ws1")
        assert found is not None
        assert found["name"] == "Test"

    def test_find_by_content_hash(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_repo.create(
            meme_id=create_meme_id(), workspace_id="ws1", attachment_id=att_id,
            content_hash="hash123", name="Test", description="test",
        )
        results = meme_repo.find_by_content_hash("hash123", "ws1")
        assert len(results) >= 1

    def test_list_enabled(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_repo.create(meme_id=create_meme_id(), workspace_id="ws1", attachment_id=att_id, content_hash="a", name="A", description="a")
        results = meme_repo.list_enabled("ws1")
        assert len(results) >= 1

    def test_record_use(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_id = create_meme_id()
        meme_repo.create(meme_id=meme_id, workspace_id="ws1", attachment_id=att_id, content_hash="a", name="A", description="a")
        meme_repo.record_use(meme_id, "ws1")
        record = meme_repo.get(meme_id, "ws1")
        assert record is not None
        assert record["use_count"] == 1
        assert record["last_used_at"] is not None

    def test_update(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_id = create_meme_id()
        meme_repo.create(meme_id=meme_id, workspace_id="ws1", attachment_id=att_id, content_hash="a", name="Old", description="old")
        meme_repo.update(meme_id, "ws1", name="New", description="new")
        record = meme_repo.get(meme_id, "ws1")
        assert record is not None
        assert record["name"] == "New"

    def test_delete(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att_id = _store_attachment(db, _create_test_image())
        meme_id = create_meme_id()
        meme_repo.create(meme_id=meme_id, workspace_id="ws1", attachment_id=att_id, content_hash="a", name="Del", description="del")
        assert meme_repo.delete(meme_id, "ws1")
        assert meme_repo.get(meme_id, "ws1") is None

    def test_workspace_isolation(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db, "ws1")
        _ensure_workspace(db, "ws2")
        att1 = _store_attachment(db, _create_test_image(), "ws1")
        att2 = _store_attachment(db, _create_test_image(), "ws2")
        mid = create_meme_id()
        meme_repo.create(meme_id=mid, workspace_id="ws1", attachment_id=att1, content_hash="a", name="A", description="a")
        assert meme_repo.get(mid, "ws2") is None
        assert meme_repo.get(mid, "ws1") is not None


# ═══════════════════════════════════════════════════════════════════════════
# 3. Register Meme (manual, no VLM)
# ═══════════════════════════════════════════════════════════════════════════


class TestRegisterMeme:
    def test_register_manual_no_vlm(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        _ensure_workspace(db)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        assert meme.name == "Doge"
        assert meme.source == "manual"
        assert fake_vlm.call_count == 0  # VLM NOT called

    def test_register_can_query(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        results = meme_svc.search_memes("Doge", "ws1")
        assert len(results) >= 1
        assert results[0]["name"] == "Doge"

    def test_duplicate_attachment_no_duplicate(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme1 = meme_svc.register_meme(sample_att_id, "First", "desc", "ws1")
        meme2 = meme_svc.register_meme(sample_att_id, "Second", "desc2", "ws1")
        assert meme1.id == meme2.id  # Same attachment = same meme returned

    def test_same_content_hash_reuses(self, meme_svc: MemeService, db: Database, sample_png: bytes):
        _ensure_workspace(db)
        att1 = _store_attachment(db, sample_png)
        att2 = _store_attachment(db, sample_png)
        meme1 = meme_svc.register_meme(att1, "Meme1", "desc", "ws1")
        meme2 = meme_svc.register_meme(att2, "Meme2", "desc2", "ws1")
        assert meme1.id == meme2.id  # Same content hash

    def test_non_image_attachment_rejected(self, meme_svc: MemeService, db: Database):
        _ensure_workspace(db)
        with pytest.raises((ValueError, RuntimeError)):
            meme_svc.register_meme("att_nonexistent", "Test", "desc", "ws1")

    def test_cross_workspace_isolation(self, meme_svc: MemeService, db: Database, sample_png: bytes):
        _ensure_workspace(db, "ws1")
        _ensure_workspace(db, "ws2")
        att = _store_attachment(db, sample_png, "ws1")
        meme_svc.register_meme(att, "Test", "desc", "ws1")
        results = meme_svc.search_memes("Test", "ws2")
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. Analyze Meme (VLM analysis)
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeMeme:
    def test_first_analyze_calls_vlm_once(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme = meme_svc.analyze_meme(sample_att_id, "ws1")
        assert fake_vlm.call_count == 1
        assert meme.source == "vision"

    def test_repeat_analyze_hits_existing(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme_svc.analyze_meme(sample_att_id, "ws1")
        meme_svc.analyze_meme(sample_att_id, "ws1")  # repeat
        assert fake_vlm.call_count == 1  # VLM NOT called again

    def test_force_refresh_calls_vlm_again(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme_svc.analyze_meme(sample_att_id, "ws1")
        meme_svc.analyze_meme(sample_att_id, "ws1", force_refresh=True)
        assert fake_vlm.call_count == 2  # VLM called twice

    def test_invalid_json_not_saved(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter("not json at all")
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        with pytest.raises(MemeAnalysisError):
            meme_svc.analyze_meme(sample_att_id, "ws1")

    def test_vlm_without_name_gets_default(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter('{"description":"only desc"}')
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme = meme_svc.analyze_meme(sample_att_id, "ws1")
        assert meme.name == "Unnamed meme"
        assert meme.source == "vision"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Search Memes (no VLM)
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchMemes:
    def test_search_by_name(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme_svc.register_meme(sample_att_id, "Confused Dog", "Dog looking confused", "ws1", emotions=["confused"])
        results = meme_svc.search_memes("confused", "ws1")
        assert len(results) >= 1
        assert "Confused Dog" in results[0]["name"] or "confused" in str(results[0].get("emotions", []))

    def test_search_by_emotion(self, meme_svc: MemeService, db: Database, sample_png: bytes):
        _ensure_workspace(db)
        att = _store_attachment(db, sample_png)
        meme_svc.register_meme(att, "Happy", "Happy meme", "ws1", emotions=["happy", "joy"])
        results = meme_svc.search_memes("happy", "ws1")
        assert len(results) >= 1

    def test_disabled_not_in_search(self, meme_repo: MemeAssetRepository, db: Database):
        _ensure_workspace(db)
        att = _store_attachment(db, _create_test_image())
        meme_id = create_meme_id()
        meme_repo.create(meme_id=meme_id, workspace_id="ws1", attachment_id=att, content_hash="a", name="Hidden", description="hidden")
        meme_repo.update(meme_id, "ws1", enabled=0)
        results = meme_repo.search("ws1", "Hidden")
        assert len(results) == 0

    def test_search_calls_zero_vlm(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme_svc.register_meme(sample_att_id, "Test", "test", "ws1")
        meme_svc.search_memes("test", "ws1")
        assert fake_vlm.call_count == 0  # No VLM during search


# ═══════════════════════════════════════════════════════════════════════════
# 6. Send Meme (ABSOLUTELY NO VLM)
# ═══════════════════════════════════════════════════════════════════════════


class TestSendMeme:
    def test_send_finds_attachment(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        result = meme_svc.send_meme(meme.id, "ws1")
        assert result["meme_id"] == meme.id
        assert result["attachment_id"] == sample_att_id
        assert result["vision_model_called"] is False

    def test_send_no_vlm(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        for _ in range(10):
            meme_svc.send_meme(meme.id, "ws1")
        assert fake_vlm.call_count == 0  # VLM NEVER called during send

    def test_send_100_times_zero_vlm(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        for _ in range(100):
            meme_svc.send_meme(meme.id, "ws1")
        assert fake_vlm.call_count == 0

    def test_use_count_increments(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        meme_svc.send_meme(meme.id, "ws1")
        meme_svc.send_meme(meme.id, "ws1")
        record = meme_svc._meme_repo.get(meme.id, "ws1")
        assert record is not None
        assert record["use_count"] == 2

    def test_disabled_meme_cannot_send(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        meme_svc._meme_repo.update(meme.id, "ws1", enabled=0)
        with pytest.raises(MemeDisabledError):
            meme_svc.send_meme(meme.id, "ws1")

    def test_nonexistent_meme_cannot_send(self, meme_svc: MemeService, db: Database):
        with pytest.raises(MemeNotFoundError):
            meme_svc.send_meme("meme_nonexistent", "ws1")

    def test_send_with_caption(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        result = meme_svc.send_meme(meme.id, "ws1", caption="Such caption")
        assert result["caption"] == "Such caption"

    def test_send_no_storage_path_leak(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        meme = meme_svc.register_meme(sample_att_id, "Doge", "Wow", "ws1")
        result = meme_svc.send_meme(meme.id, "ws1")
        assert "storage_path" not in result


# ═══════════════════════════════════════════════════════════════════════════
# 7. End-to-End Scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestEndToEndScenarios:
    """Four critical scenario tests from the spec."""

    def test_scenario1_manual_send_no_vlm(self, meme_svc: MemeService, db: Database, sample_png: bytes):
        """Manual register + 10 sends = 0 VLM calls."""
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        att = _store_attachment(db, sample_png)
        meme = meme_svc.register_meme(att, "Doge", "Wow", "ws1")
        assert fake_vlm.call_count == 0
        for _ in range(10):
            meme_svc.send_meme(meme.id, "ws1")
        assert fake_vlm.call_count == 0
        # No exception means success

    def test_scenario2_analyze_then_send(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        """analyze_meme (1 VLM) + 10 sends (0 VLM) = 1 VLM total."""
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme = meme_svc.analyze_meme(sample_att_id, "ws1")
        assert fake_vlm.call_count == 1
        assert meme.source == "vision"
        for _ in range(10):
            meme_svc.send_meme(meme.id, "ws1")
        assert fake_vlm.call_count == 1  # Still 1 — sends don't call VLM

    def test_scenario3_inspect_image_for_new_detail(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        """User asks for new visual detail → inspect_image may be called."""
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme = meme_svc.analyze_meme(sample_att_id, "ws1")
        assert fake_vlm.call_count == 1
        # Simulate explicit inspect_image call
        fake_vs.inspect_image(sample_att_id, "What does the small text say?", "ws1")
        assert fake_vlm.call_count == 2  # Explicit inspect_image

    def test_scenario4_search_then_send_no_vlm(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        """User asks for 'confused meme' → search → send → 0 VLM."""
        _ensure_workspace(db)
        fake_vlm = FakeVisionAdapter()
        fake_vs = FakeVisionService(fake_vlm)
        meme_svc.set_vision_service(fake_vs)
        meme_svc.register_meme(sample_att_id, "Confused Dog", "Shows confusion", "ws1", emotions=["confused"])
        results = meme_svc.search_memes("confused", "ws1")
        assert len(results) >= 1
        meme_id = results[0]["meme_id"]
        result = meme_svc.send_meme(meme_id, "ws1")
        assert result["vision_model_called"] is False
        assert fake_vlm.call_count == 0


# ═══════════════════════════════════════════════════════════════════════════
# 8. Capability Manifests
# ═══════════════════════════════════════════════════════════════════════════


class TestCapabilityManifests:
    def test_register_meme_manifest(self):
        assert REGISTER_MEME_MANIFEST.name == "register_meme"
        assert "attachment_id" in REGISTER_MEME_MANIFEST.input_schema.get("required", [])

    def test_analyze_meme_manifest(self):
        assert ANALYZE_MEME_MANIFEST.name == "analyze_meme"
        assert "force_refresh" in ANALYZE_MEME_MANIFEST.input_schema.get("properties", {})

    def test_search_memes_manifest(self):
        assert SEARCH_MEMES_MANIFEST.name == "search_memes"
        assert SEARCH_MEMES_MANIFEST.input_schema["properties"]["limit"]["maximum"] == 20

    def test_send_meme_manifest(self):
        assert SEND_MEME_MANIFEST.name == "send_meme"
        assert "meme_id" in SEND_MEME_MANIFEST.input_schema.get("required", [])

    def test_capability_registration(self, meme_svc: MemeService):
        cap_reg = CapabilityRegistry()
        meme_svc.register_with_capability_registry(cap_reg)
        for name in ("register_meme", "analyze_meme", "search_memes", "send_meme"):
            manifest = cap_reg.get_manifest(name)
            assert manifest is not None, f"{name} not registered"

    def test_register_meme_by_capability(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        cap_reg = CapabilityRegistry()
        meme_svc.register_with_capability_registry(cap_reg)
        meme_svc.set_current_context(workspace_id="ws1")
        result = cap_reg.invoke("register_meme",
            attachment_id=sample_att_id, name="CapMeme", description="via reg")
        assert result is not None, f"Expected ok result, got: {result}"
        if result.status != "ok":
            assert False, f"Expected ok, got {result.status}: {result.summary} {result.error}"
        assert result.status == "ok"

    def test_send_meme_by_capability(self, meme_svc: MemeService, db: Database, sample_att_id: str):
        _ensure_workspace(db)
        cap_reg = CapabilityRegistry()
        meme_svc.register_with_capability_registry(cap_reg)
        meme = meme_svc.register_meme(sample_att_id, "CapMeme", "desc", "ws1")
        meme_svc.set_current_context(workspace_id="ws1")
        result = cap_reg.invoke("send_meme", meme_id=meme.id)
        assert result is not None, f"Expected ok, got: {result}"
        if result.status != "ok":
            assert False, f"Expected ok, got {result.status}: {result.summary} {result.error}"
        assert result.status == "ok"
        assert result.data is not None
        assert result.data.get("vision_model_called") is False


# ═══════════════════════════════════════════════════════════════════════════
# 9. API Contract
# ═══════════════════════════════════════════════════════════════════════════


class TestMemeAPI:
    def test_create_meme_model(self):
        from cogito_agent.api.app import CreateMemeRequest
        req = CreateMemeRequest(
            attachment_id="att_xxx", name="Test", description="test",
            emotions=["happy"], aliases=["joy"],
        )
        assert req.name == "Test"
        assert req.emotions == ["happy"]

    def test_update_meme_model(self):
        from cogito_agent.api.app import UpdateMemeRequest
        req = UpdateMemeRequest(name="New", enabled=False)
        assert req.name == "New"
        assert req.enabled is False
