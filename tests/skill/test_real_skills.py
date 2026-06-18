from __future__ import annotations

import uuid

import pytest

from cogito_agent.skill.builtin import (
    run_daily_brief,
    run_inbox_digest,
    run_memory_consolidation,
    run_task_extraction,
    run_trace_review,
)
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    ws = WorkspaceRepository(database)
    ws.create("default", "default")
    return database


@pytest.fixture
def db_with_data(db: Database) -> Database:
    db.connection.execute(
        "INSERT INTO sessions (id, workspace_id, title)"
        " VALUES (?, ?, ?)",
        (str(uuid.uuid4()), "default", "Test Session"),
    )
    for i in range(3):
        db.connection.execute(
            "INSERT INTO memories (id, workspace_id, type, text, confidence,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (str(uuid.uuid4()), "default",
             "task" if i < 2 else "general",
             f"Test task memory {i}" if i < 2 else f"General memory {i}",
             0.5 + i * 0.1),
        )
    for i in range(2):
        db.connection.execute(
            "INSERT INTO inbox_items (id, workspace_id, title, body, source)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "default", f"Inbox item {i}", f"Body {i}", "test"),
        )
    for i in range(2):
        db.connection.execute(
            "INSERT INTO artifacts (id, workspace_id, source_type, source_id,"
            " title, artifact_type, content_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (str(uuid.uuid4()), "default", "test", "test",
             f"Artifact {i}", "text", "{}"),
        )
    for i in range(2):
        root_id = str(uuid.uuid4())
        fid = str(uuid.uuid4())
        db.connection.execute(
            "INSERT INTO workspace_roots (id, workspace_id, root_path,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (root_id, "default", "/tmp/test"),
        )
        db.connection.execute(
            "INSERT INTO workspace_files (id, workspace_id, root_id, relative_path,"
            " file_name, mime_type, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'active', datetime('now'), datetime('now'))",
            (fid, "default", root_id, f"test_{i}.md",
             f"test_{i}.md", "text/markdown"),
        )
        db.connection.execute(
            "INSERT INTO file_chunks (id, workspace_file_id, workspace_id,"
            " chunk_index, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), fid, "default", 0, f"File chunk content {i}"),
        )
    db.connection.commit()
    return db


class TestDailyBrief:
    def test_daily_brief_real_run(self, db_with_data: Database) -> None:
        result = run_daily_brief(db_with_data, workspace_id="default")
        assert result["status"] == "completed"
        assert result["trace_id"]
        assert result["artifact_id"]
        assert "summary" in result

    def test_daily_brief_with_custom_date(self, db_with_data: Database) -> None:
        result = run_daily_brief(
            db_with_data, workspace_id="default", date="2026-06-18",
        )
        assert result["status"] == "completed"

    def test_daily_brief_inbox_notification(self, db_with_data: Database) -> None:
        run_daily_brief(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM inbox_items WHERE source = 'skill.daily_brief'"
        ).fetchall()
        assert len(rows) >= 1

    def test_daily_brief_creates_artifact(self, db_with_data: Database) -> None:
        result = run_daily_brief(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (result["artifact_id"],),
        ).fetchall()
        assert len(rows) == 1

    def test_daily_brief_trace(self, db_with_data: Database) -> None:
        result = run_daily_brief(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (result["trace_id"],)
        ).fetchall()
        assert len(rows) == 1

    def test_daily_brief_audit(self, db_with_data: Database) -> None:
        run_daily_brief(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM audit_logs WHERE action LIKE '%daily_brief%'"
        ).fetchall()
        assert len(rows) >= 1


class TestMemoryConsolidation:
    def test_memory_consolidation_proposal_only(self, db: Database) -> None:
        for i in range(3):
            db.connection.execute(
                "INSERT INTO memories (id, workspace_id, type, text, confidence,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (str(uuid.uuid4()), "default", "general",
                 "Duplicate text to merge", 0.5),
            )
        db.connection.commit()
        result = run_memory_consolidation(db, workspace_id="default")
        assert result["status"] == "completed"
        assert result["proposal_count"] >= 1
        proposals = result["proposals"]
        assert any(p["action"] == "merge" for p in proposals)

    def test_memory_consolidation_no_direct_mutation(self, db: Database) -> None:
        """Consolidation must NOT delete/alter memories directly (proposal-only)."""
        mid = str(uuid.uuid4())
        db.connection.execute(
            "INSERT INTO memories (id, workspace_id, type, text, confidence, status,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'active', datetime('now'), datetime('now'))",
            (mid, "default", "general", "Test memory", 0.5),
        )
        db.connection.commit()
        run_memory_consolidation(db, workspace_id="default")
        row = db.connection.execute(
            "SELECT * FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None, "memory must NOT be deleted"
        assert str(row["text"]) == "Test memory", "memory text must NOT change"
        assert str(row["status"]) == "active", "memory status must NOT change"
        row_count = int(db.connection.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE id = ? AND deleted_at IS NULL",
            (mid,),
        ).fetchone()["cnt"])
        assert row_count == 1, "memory must still exist (not soft-deleted)"

    def test_memory_consolidation_artifact(self, db: Database) -> None:
        result = run_memory_consolidation(db, workspace_id="default")
        rows = db.connection.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (result["artifact_id"],),
        ).fetchall()
        assert len(rows) == 1

    def test_memory_consolidation_trace(self, db: Database) -> None:
        result = run_memory_consolidation(db, workspace_id="default")
        rows = db.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (result["trace_id"],)
        ).fetchall()
        assert len(rows) == 1

    def test_memory_consolidation_finds_stale(self, db: Database) -> None:
        db.connection.execute(
            "INSERT INTO memories (id, workspace_id, type, text,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, datetime('now', '-60 days'),"
            " datetime('now', '-60 days'))",
            (str(uuid.uuid4()), "default", "general", "Old memory"),
        )
        db.connection.commit()
        result = run_memory_consolidation(db, workspace_id="default")
        assert any(p["action"] == "archive" for p in result["proposals"])

    def test_memory_consolidation_low_confidence(self, db: Database) -> None:
        db.connection.execute(
            "INSERT INTO memories (id, workspace_id, type, text, confidence,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (str(uuid.uuid4()), "default", "general", "Low confidence memory", 0.1),
        )
        db.connection.commit()
        result = run_memory_consolidation(db, workspace_id="default")
        assert any(p["action"] == "flag" for p in result["proposals"])

    def test_memory_consolidation_workspace_isolation(self, db: Database) -> None:
        ws = WorkspaceRepository(db)
        ws.create("ws2", "ws2")
        db.connection.execute(
            "INSERT INTO memories (id, workspace_id, type, text,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (str(uuid.uuid4()), "ws2", "general", "WS2 memory"),
        )
        db.connection.commit()
        result = run_memory_consolidation(db, workspace_id="ws2")
        for p in result["proposals"]:
            for sid in p["source_memory_ids"]:
                row = db.connection.execute(
                    "SELECT workspace_id FROM memories WHERE id = ?", (sid,)
                ).fetchone()
                if row:
                    assert row["workspace_id"] == "ws2"


class TestTaskExtraction:
    def test_task_extraction_candidates(self, db_with_data: Database) -> None:
        result = run_task_extraction(db_with_data, workspace_id="default")
        assert result["status"] == "completed"
        assert result["candidate_count"] >= 1

    def test_task_extraction_creates_artifact(self, db_with_data: Database) -> None:
        result = run_task_extraction(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (result["artifact_id"],),
        ).fetchall()
        assert len(rows) == 1

    def test_task_extraction_no_direct_write(self, db_with_data: Database) -> None:
        before = db_with_data.connection.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE type = 'task'"
        ).fetchone()
        run_task_extraction(db_with_data, workspace_id="default")
        after = db_with_data.connection.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE type = 'task'"
        ).fetchone()
        assert int(after["cnt"]) == int(before["cnt"])

    def test_task_extraction_trace(self, db_with_data: Database) -> None:
        result = run_task_extraction(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (result["trace_id"],)
        ).fetchall()
        assert len(rows) == 1

    def test_task_extraction_audit(self, db_with_data: Database) -> None:
        run_task_extraction(db_with_data, workspace_id="default")
        rows = db_with_data.connection.execute(
            "SELECT * FROM audit_logs WHERE action LIKE '%task_extraction%'"
        ).fetchall()
        assert len(rows) >= 1


class TestTraceReview:
    def test_trace_review_health_report(self, db: Database) -> None:
        trace_id = str(uuid.uuid4())
        db.connection.execute(
            "INSERT INTO traces (id, workspace_id, root_event_id, status)"
            " VALUES (?, ?, ?, 'failed')",
            (trace_id, "default", "test_event"),
        )
        db.connection.execute(
            "INSERT INTO tool_calls (id, trace_id, capability_name, decision)"
            " VALUES (?, ?, ?, 'deny')",
            (str(uuid.uuid4()), trace_id, "test.tool"),
        )
        db.connection.execute(
            "INSERT INTO approval_records"
            " (id, workspace_id, actor_id, capability_name, status)"
            " VALUES (?, ?, ?, ?, 'pending')",
            (str(uuid.uuid4()), "default", "test", "test.cap"),
        )
        db.connection.commit()
        result = run_trace_review(db, workspace_id="default")
        assert result["status"] == "completed"
        assert result["issue_count"] >= 1

    def test_trace_review_no_issues(self, db: Database) -> None:
        result = run_trace_review(db, workspace_id="default")
        assert result["status"] == "completed"
        assert result["issue_count"] == 0

    def test_trace_review_trace(self, db: Database) -> None:
        result = run_trace_review(db, workspace_id="default")
        rows = db.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (result["trace_id"],)
        ).fetchall()
        assert len(rows) == 1


class TestInboxDigest:
    def test_inbox_digest_aggregation(self, db: Database) -> None:
        for i in range(5):
            db.connection.execute(
                "INSERT INTO inbox_items (id, workspace_id, title, body, source)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "default", f"Item {i}", f"Body {i}", "test"),
            )
        db.connection.commit()
        result = run_inbox_digest(db, workspace_id="default")
        assert result["status"] == "completed"
        assert result["item_count"] == 5

    def test_inbox_digest_no_recursive_spam(self, db: Database) -> None:
        """Digest must NOT create inbox notifications (would cause recursive spam)."""
        for i in range(5):
            db.connection.execute(
                "INSERT INTO inbox_items (id, workspace_id, title, body, source)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "default", f"Item {i}", f"Body {i}", "test"),
            )
        db.connection.commit()
        before = int(db.connection.execute(
            "SELECT COUNT(*) as cnt FROM inbox_items"
        ).fetchone()["cnt"])
        assert before == 5

        run_inbox_digest(db, workspace_id="default")

        after = int(db.connection.execute(
            "SELECT COUNT(*) as cnt FROM inbox_items"
        ).fetchone()["cnt"])
        assert after == before, "inbox_digest must NOT create inbox items (recursive spam)"

    def test_inbox_digest_identifies_noisy_sources(self, db: Database) -> None:
        for _ in range(5):
            db.connection.execute(
                "INSERT INTO inbox_items (id, workspace_id, title, body, source)"
                " VALUES (?, ?, ?, ?, 'noisy_source')",
                (str(uuid.uuid4()), "default", "Noisy", "Lots of items"),
            )
        db.connection.commit()
        result = run_inbox_digest(db, workspace_id="default")
        assert len(result["noisy_sources"]) >= 1
        sources = [str(ns["source"]) for ns in result["noisy_sources"]]
        assert "noisy_source" in sources

    def test_inbox_digest_trace(self, db: Database) -> None:
        result = run_inbox_digest(db, workspace_id="default")
        rows = db.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (result["trace_id"],)
        ).fetchall()
        assert len(rows) == 1

    def test_inbox_digest_audit(self, db: Database) -> None:
        run_inbox_digest(db, workspace_id="default")
        rows = db.connection.execute(
            "SELECT * FROM audit_logs WHERE action LIKE '%inbox_digest%'"
        ).fetchall()
        assert len(rows) >= 1
