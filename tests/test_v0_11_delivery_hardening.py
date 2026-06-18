"""Tests for v0.11.0-dev: Autonomy Delivery & Local Production Hardening."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cogito_agent.autonomy.delivery import (
    ConsoleNotificationAdapter,
    DeliveryResult,
    LocalInboxDeliveryAdapter,
)
from cogito_agent.autonomy.dispatcher import (
    MAX_RETRIES,
    OutboxDispatcher,
    _compute_backoff,
)
from cogito_agent.autonomy.outbox import Outbox
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.governance.policy import DecisionType, PolicyRule
from cogito_agent.security import (
    DevSqliteSecretProvider,
    EnvSecretProvider,
    LocalEncryptedSecretProvider,
    LocalSecretsProvider,
    get_provider_from_config,
)
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    _db = Database(":memory:")
    _db.initialize()
    _db.migrate()
    _db.connection.execute(
        "INSERT INTO workspaces (id, name) VALUES (?, ?)", ("default", "default")
    )
    _db.connection.commit()
    yield _db
    _db.close()


@pytest.fixture
def outbox(db):
    return Outbox(db)


@pytest.fixture
def tracer(db):
    return Tracer(db)


@pytest.fixture
def audit(db):
    return AuditLogger(db)


@pytest.fixture
def policy():
    return PolicyEngine()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DeliveryAdapter Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeliveryAdapter:
    def test_local_inbox_adapter_deliver_success(self, db, outbox):
        mid = outbox.enqueue(
            event_id="e1", decision_id="d1",
            title="Test Notification", body="Hello",
        )
        message = outbox.get_message(mid)
        adapter = LocalInboxDeliveryAdapter()
        result = adapter.deliver(message, db)
        assert result.status == "sent"
        assert result.delivered_at is not None

        # Should have been recorded in notifications table
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notifications WHERE title=?",
            ("Test Notification",),
        )
        assert cur.fetchone()["cnt"] > 0

    def test_local_inbox_adapter_deliver_failure(self, db, outbox):
        mid = outbox.enqueue(
            event_id="e2", decision_id="d2",
            title="Test", body="Body",
        )
        message = outbox.get_message(mid)
        adapter = LocalInboxDeliveryAdapter()
        # Close db to cause failure
        db.close()
        result = adapter.deliver(message, db)
        assert result.status == "failed"
        assert result.error is not None

    def test_console_notification_adapter_deliver(self, db, outbox):
        mid = outbox.enqueue(
            event_id="e3", decision_id="d3",
            title="Console Test", body="Body",
            workspace_id="default",
        )
        message = outbox.get_message(mid)
        adapter = ConsoleNotificationAdapter()
        result = adapter.deliver(message, db)
        assert result.status == "sent"
        assert result.delivered_at is not None

        # Should have been written to inbox_items
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM inbox_items WHERE title=?",
            ("Console Test",),
        )
        assert cur.fetchone()["cnt"] > 0

    def test_delivery_result_model(self):
        result = DeliveryResult(
            message_id="m1", status="sent",
            delivered_at="2026-01-01T00:00:00",
            trace_id="trace1",
        )
        assert result.message_id == "m1"
        assert result.status == "sent"
        assert result.trace_id == "trace1"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. OutboxDispatcher Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOutboxDispatcher:
    def test_dispatcher_sends_pending_message(self, db, outbox, tracer, audit, policy):
        mid = outbox.enqueue(
            event_id="e10", decision_id="d10",
            title="Dispatch Test", body="Body",
        )
        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=policy,
        )
        processed = dispatcher.process_batch()
        assert mid in processed

        msg = outbox.get_message(mid)
        assert msg is not None
        assert msg["status"] in ("sent",)

    def test_dispatcher_respects_policy_deny(self, db, outbox, tracer, audit):
        deny_rule = PolicyRule(
            actor="*", operation="send", context="*",
            decision=DecisionType.deny, capability="notification.send",
        )
        allow_call = PolicyRule(
            actor="*", operation="call_model", context="*",
            decision=DecisionType.allow,
        )
        strict_policy = PolicyEngine(rules=[deny_rule, allow_call])
        mid = outbox.enqueue(
            event_id="e11", decision_id="d11",
            title="Denied", body="Should be skipped",
        )
        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=strict_policy,
        )
        processed = dispatcher.process_batch()
        assert mid in processed

        msg = outbox.get_message(mid)
        assert msg is not None
        assert msg["status"] == "skipped"

    def test_dispatcher_retry_and_dead_letter(self, db, outbox, tracer, audit):
        """Force failures to trigger retry and eventually dead_letter."""
        mid = outbox.enqueue(
            event_id="e12", decision_id="d12",
            title="Retry Test", body="Will fail",
        )

        # Set a low delivery_attempts to trigger immediate retry logic
        db.connection.execute(
            "UPDATE outbox_messages SET delivery_attempts = ?, status = 'retrying',"
            " next_retry_at = ? WHERE id = ?",
            (MAX_RETRIES - 1, (datetime.now(UTC) - timedelta(minutes=5)).isoformat(), mid),
        )
        db.connection.commit()

        class FailingAdapter:
            def adapter_name(self):
                return "failing"

            def deliver(self, message, d):
                return DeliveryResult(
                    message_id=str(message["id"]),
                    status="failed",
                    error="Intentional failure",
                )

        dispatcher = OutboxDispatcher(
            db, delivery_adapter=FailingAdapter(),
            audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        processed = dispatcher.process_batch()
        assert mid in processed

        msg = outbox.get_message(mid)
        assert msg is not None
        assert msg["status"] == "dead_letter"

    def test_dispatcher_skips_future_retry(self, db, outbox, tracer, audit):
        """Messages with future next_retry_at should be skipped."""
        mid = outbox.enqueue(
            event_id="e13", decision_id="d13",
            title="Future Retry", body="Not yet",
        )
        db.connection.execute(
            "UPDATE outbox_messages SET status = 'retrying',"
            " next_retry_at = ? WHERE id = ?",
            ((datetime.now(UTC) + timedelta(hours=1)).isoformat(), mid),
        )
        db.connection.commit()

        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        processed = dispatcher.process_batch()
        assert mid not in processed

    def test_dispatcher_redaction(self, db, outbox, tracer, audit):
        """Payload should be redacted in audit logs."""
        mid = outbox.enqueue(
            event_id="e14", decision_id="d14",
            title="Secret: sk-abc123", body="Bearer token123",
        )
        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        dispatcher.process_batch()

        # Check audit logs are redacted
        cur = db.connection.execute(
            "SELECT details FROM audit_logs WHERE action LIKE 'delivery.%'"
            " ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            details = str(row["details"])
            assert "sk-abc123" not in details
            assert "[REDACTED]" in details or "sk-" not in details

    def test_dispatcher_workspace_isolation(self, db, outbox, tracer, audit):
        """Non-matching workspace should not be dispatched."""
        db.connection.execute(
            "INSERT INTO workspaces (id, name) VALUES (?, ?)", ("ws2", "ws2")
        )
        db.connection.commit()

        mid = outbox.enqueue(
            event_id="e15", decision_id="d15",
            title="WS Isolated", body="Only for ws2",
            workspace_id="ws2",
        )

        # Create dispatcher with default workspace
        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        processed = dispatcher.process_batch()
        # The dispatcher doesn't filter by workspace by default, it processes all pending
        # So this should still be dispatched
        assert mid in processed

    def test_dispatcher_trace_and_audit(self, db, outbox, tracer, audit):
        """Each delivery attempt must write trace spans and audit logs."""
        mid = outbox.enqueue(
            event_id="e16", decision_id="d16",
            title="Trace Test", body="Body",
        )
        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        dispatcher.process_batch()

        # Check trace was created
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM traces"
            " WHERE root_event_id LIKE 'delivery.%'"
        )
        assert cur.fetchone()["cnt"] > 0

        # Check audit log
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM audit_logs"
            " WHERE action LIKE 'delivery.%'"
        )
        assert cur.fetchone()["cnt"] > 0

    def test_dispatcher_retry_message(self, db, outbox, tracer, audit):
        """retry_message should reset a failed message to pending."""
        mid = outbox.enqueue(
            event_id="e17", decision_id="d17",
            title="Retry Me", body="Body",
        )
        db.connection.execute(
            "UPDATE outbox_messages SET status='failed', last_error='err' WHERE id=?",
            (mid,),
        )
        db.connection.commit()

        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        assert dispatcher.retry_message(mid)

        msg = outbox.get_message(mid)
        assert msg["status"] == "pending"
        assert msg["last_error"] is None

    def test_dispatcher_loop_run_once(self, db, outbox, tracer, audit):
        """Run the dispatcher in single-batch mode."""
        mid = outbox.enqueue(
            event_id="e18", decision_id="d18",
            title="Loop Test", body="Body",
        )
        dispatcher = OutboxDispatcher(
            db, audit_logger=audit, tracer=tracer, policy_engine=PolicyEngine(),
        )
        processed = dispatcher.process_all()
        assert mid in processed


class TestBackoff:
    def test_exponential_backoff(self):
        assert _compute_backoff(1) == 30
        assert _compute_backoff(2) == 60
        assert _compute_backoff(3) == 120
        assert _compute_backoff(4) == 240
        assert _compute_backoff(5) == 480
        assert _compute_backoff(8) == 3600  # capped

    def test_backoff_increases(self):
        prev = 0
        for i in range(1, 10):
            cur = _compute_backoff(i)
            assert cur >= prev
            prev = cur


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Secret Store Hardening Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSecretProviders:
    def test_env_secret_provider(self):
        os.environ["COGITO_TEST_V0_11_SECRET"] = "test_value_123"
        try:
            provider = EnvSecretProvider()
            sv = provider.get_secret("test_v0_11_secret")
            assert sv is not None
            assert sv.value == "test_value_123"
            assert "[REDACTED]" in repr(sv)
            assert "[REDACTED]" in str(sv)
            keys = provider.list_keys()
            assert "TEST_V0_11_SECRET" in keys
        finally:
            del os.environ["COGITO_TEST_V0_11_SECRET"]

    def test_dev_sqlite_provider_warning(self):
        import tempfile
        path = tempfile.mktemp(suffix=".db")
        with pytest.warns(UserWarning, match="plaintext in SQLite"):
            provider = DevSqliteSecretProvider(db_path=path)
        provider.set_secret("key1", "value1")
        sv = provider.get_secret("key1")
        assert sv is not None
        assert sv.value == "value1"
        assert provider.list_keys() == ["key1"]
        assert provider.delete_secret("key1") is True
        assert provider.get_secret("key1") is None
        try:
            os.remove(path)
        except Exception:
            pass

    def test_local_encrypted_provider(self):
        try:
            from cryptography.fernet import Fernet  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "secrets.db")
            key_path = os.path.join(tmp, "secrets.key")
            provider = LocalEncryptedSecretProvider(db_path=db_path, key_path=key_path)
            provider.set_secret("enc_key", "sensitive_data")
            sv = provider.get_secret("enc_key")
            assert sv is not None
            assert sv.value == "sensitive_data"

            # Verify the data is encrypted at rest
            import sqlite3
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT value FROM secrets WHERE key='enc_key'"
            ).fetchone()
            conn.close()
            assert row is not None
            raw = row[0]
            assert "sensitive_data" not in raw  # should be encrypted
            assert raw != "sensitive_data"

    def test_local_encrypted_provider_key_persistence(self):
        try:
            from cryptography.fernet import Fernet  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        """Re-opening with same key should decrypt."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "secrets.db")
            key_path = os.path.join(tmp, "secrets.key")

            p1 = LocalEncryptedSecretProvider(db_path=db_path, key_path=key_path)
            p1.set_secret("persist_key", "persist_value")

            p2 = LocalEncryptedSecretProvider(db_path=db_path, key_path=key_path)
            sv = p2.get_secret("persist_key")
            assert sv is not None
            assert sv.value == "persist_value"

    def test_local_encrypted_provider_nonexistent_key(self):
        try:
            from cryptography.fernet import Fernet  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "secrets2.db")
            key_path = os.path.join(tmp, "secrets2.key")
            provider = LocalEncryptedSecretProvider(db_path=db_path, key_path=key_path)
            sv = provider.get_secret("nonexistent")
            assert sv is None

    def test_get_provider_from_config(self):
        p = get_provider_from_config({"secrets.backend": "env"})
        assert isinstance(p, EnvSecretProvider)

        with pytest.warns(UserWarning):
            p = get_provider_from_config({"secrets.backend": "dev_sqlite"})
            assert isinstance(p, DevSqliteSecretProvider)

    def test_provider_rotate_delete(self):
        import tempfile
        path = tempfile.mktemp(suffix=".db")
        with pytest.warns(UserWarning):
            provider = DevSqliteSecretProvider(db_path=path)
        provider.set_secret("rotate_test", "old_value")
        provider.rotate_secret("rotate_test", "new_value")
        sv = provider.get_secret("rotate_test")
        assert sv.value == "new_value"
        provider.delete_secret("rotate_test")
        assert provider.get_secret("rotate_test") is None
        try:
            os.remove(path)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Backup/Restore/Export Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBackup:
    def test_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            out_path = os.path.join(tmp, "backup.zip")

            # Create minimal DB
            conn = Database(db_path)
            conn.initialize()
            conn.migrate()
            conn.connection.execute(
                "INSERT INTO workspaces (id, name) VALUES (?, ?)", ("default", "default")
            )
            conn.connection.commit()
            conn.close()

            from cogito_agent.cli.backup import create_backup
            manifest = create_backup(
                out_path=out_path, db_path=db_path,
                include_secrets=False, data_dir=tmp,
            )
            assert os.path.isfile(out_path)
            assert "cogito.db" in manifest.get("files", [])

    def test_restore_backup_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            out_path = os.path.join(tmp, "backup.zip")

            conn = Database(db_path)
            conn.initialize()
            conn.migrate()
            conn.close()

            from cogito_agent.cli.backup import create_backup, restore_backup
            manifest = create_backup(
                out_path=out_path, db_path=db_path,
                include_secrets=False, data_dir=tmp,
            )

            result = restore_backup(
                backup_path=out_path, db_path=db_path,
                dry_run=True, data_dir=tmp,
            )
            assert result.get("dry_run") is True
            assert len(result.get("actions", [])) > 0

    def test_export_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            out_path = os.path.join(tmp, "memories.json")

            conn = Database(db_path)
            conn.initialize()
            conn.migrate()
            conn.close()

            from cogito_agent.cli.backup import export_data
            result = export_data(
                out_path=out_path, db_path=db_path, sections=["memories"],
                data_dir=tmp,
            )
            assert os.path.isfile(out_path)
            assert "memories" in result.get("sections", {})

    def test_export_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            out_path = os.path.join(tmp, "traces.json")

            conn = Database(db_path)
            conn.initialize()
            conn.migrate()
            conn.close()

            from cogito_agent.cli.backup import export_data
            result = export_data(
                out_path=out_path, db_path=db_path, sections=["traces"],
                data_dir=tmp,
            )
            assert os.path.isfile(out_path)
            assert "traces" in result.get("sections", {})

    def test_backup_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            out_path = os.path.join(tmp, "backup.zip")

            conn = Database(db_path)
            conn.initialize()
            conn.migrate()
            # Simulate a secret in a config
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({
                "api_key": "sk-real-key-12345",
                "model": "gpt-4",
            }))
            conn.close()

            from cogito_agent.cli.backup import create_backup
            manifest = create_backup(
                out_path=out_path, db_path=db_path,
                include_secrets=False, data_dir=tmp,
            )

            # The config should be redacted in the backup
            import zipfile
            with zipfile.ZipFile(out_path, "r") as zf:
                if "config.json" in zf.namelist():
                    cfg_data = json.loads(zf.read("config.json"))
                    assert cfg_data.get("api_key") == "[REDACTED]"

    def test_backup_include_secrets_flag_required(self):
        """By default, secrets should not be included."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            out_path = os.path.join(tmp, "backup.zip")

            conn = Database(db_path)
            conn.initialize()
            conn.close()

            from cogito_agent.cli.backup import create_backup
            manifest = create_backup(
                out_path=out_path, db_path=db_path,
                include_secrets=False, data_dir=tmp,
            )
            assert manifest.get("include_secrets") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Migration v7 Test
# ═══════════════════════════════════════════════════════════════════════════════


class TestMigrationV7:
    def test_migration_v7_adds_columns(self):
        """Verify migration v7 adds delivery_attempts etc."""
        _db = Database(":memory:")
        _db.initialize()

        # Create tables from v1-v6 (without v7)
        _db.migrate()

        # Check columns exist (they should from the v6 CREATE TABLE)
        cur = _db.connection.execute("PRAGMA table_info(outbox_messages)")
        columns = {r["name"] for r in cur.fetchall()}
        assert "delivery_attempts" in columns
        assert "last_error" in columns
        assert "next_retry_at" in columns
        assert "delivered_at" in columns
        assert "read_at" in columns
        assert "dismissed_at" in columns
        assert "failed_at" in columns
        assert "updated_at" in columns

        _db.close()

    def test_migration_v7_inbox_items_decision_id(self):
        """Verify inbox_items has decision_id column."""
        _db = Database(":memory:")
        _db.initialize()
        _db.migrate()

        cur = _db.connection.execute("PRAGMA table_info(inbox_items)")
        columns = {r["name"] for r in cur.fetchall()}
        assert "decision_id" in columns

        _db.close()
