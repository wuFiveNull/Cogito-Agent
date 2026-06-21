from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cogito_agent.autonomy import AutonomyChannel, AutonomyEvent, normalize_from_dict
from cogito_agent.autonomy.gate import NotificationGate
from cogito_agent.storage import Database, WorkspaceRepository


def test_normalizer_supports_channel_ttl_evidence_and_ack() -> None:
    event = normalize_from_dict(
        {
            "title": "Build failed",
            "channel": "alert",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "evidence": [{"run_id": "run-1"}],
            "ack_token": "ack-1",
        }
    )
    assert event.channel == AutonomyChannel.alert
    assert event.expires_at is not None
    assert event.evidence == [{"run_id": "run-1"}]
    assert event.ack_token == "ack-1"


def test_expired_event_is_skipped_before_other_gate_checks() -> None:
    db = Database()
    db.initialize()
    db.migrate()
    WorkspaceRepository(db).create("workspace", "test")
    try:
        event = AutonomyEvent(
            workspace_id="workspace",
            title="Old event",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        decision = NotificationGate(db).evaluate(event)
        assert decision.action.value == "skip"
        assert decision.reason_code == "expired"
    finally:
        db.close()
