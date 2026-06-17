"""Tests for autonomy CLI commands."""
from __future__ import annotations

import os
import tempfile

from cogito_agent.storage import Database


def _init_db(db_path: str) -> Database:
    db = Database(db_path)
    db.initialize()
    db.migrate()
    db.close()
    return db


def test_autonomy_emit_via_cli():
    """Integration test: emit event via CLI handler."""
    from cogito_agent.cli.autonomy_cli import run_autonomy_emit

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _init_db(db_path)
    try:
        ns = type("NS", (), {
            "db_path": db_path,
            "title": "cli test",
            "body": "hello",
            "source": "cli",
            "priority": "normal",
            "workspace_id": "*",
            "category": "test",
        })()
        run_autonomy_emit(ns)
        db = Database(db_path)
        db.initialize()
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notification_decisions"
        )
        assert cur.fetchone()["cnt"] >= 1
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_autonomy_decisions_empty():
    from cogito_agent.cli.autonomy_cli import run_autonomy_decisions

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _init_db(db_path)
    try:
        ns = type("NS", (), {
            "db_path": db_path,
            "workspace_id": "*",
            "limit": 50,
        })()
        run_autonomy_decisions(ns)
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_autonomy_outbox_empty():
    from cogito_agent.cli.autonomy_cli import run_autonomy_outbox

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _init_db(db_path)
    try:
        ns = type("NS", (), {
            "db_path": db_path,
            "workspace_id": "*",
            "limit": 50,
        })()
        run_autonomy_outbox(ns)
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_autonomy_feedback_via_cli():
    from cogito_agent.cli.autonomy_cli import run_autonomy_feedback

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _init_db(db_path)
    try:
        # need a decision first
        from cogito_agent.autonomy import DecisionStore
        db = Database(db_path)
        db.initialize()
        store = DecisionStore(db)
        store.save_decision(
            decision_id="d-cli-fb",
            event_id="e-cli-fb",
            workspace_id="*",
            user_id="",
            action="push",
            reason_code="ok",
            reason="",
            cost_score=0,
            priority_score=0,
            dedup_hit=False,
            quiet_hours_hit=False,
            quota_hit=False,
            requires_approval=False,
        )
        db.close()

        ns = type("NS", (), {
            "db_path": db_path,
            "decision_id": "d-cli-fb",
            "value": "useful",
            "comment": "nice",
            "workspace_id": "*",
        })()
        run_autonomy_feedback(ns)
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass
