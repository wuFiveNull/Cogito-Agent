from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from cogito_agent.governance import PolicyEngine
from cogito_agent.shared import DecisionType, PolicyRequest
from cogito_agent.storage import Database


class NotificationGate:
    def __init__(
        self,
        db: Database,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._db = db
        self._policy = policy_engine or PolicyEngine()

    def should_notify(
        self,
        workspace_id: str,
        title: str,
        body: str,
    ) -> tuple[bool, str]:
        now = datetime.now(UTC)
        event_hash = self._hash_event(title, body)

        if self._is_quiet_hours(workspace_id, now):
            return False, "quiet_hours"

        if self._is_duplicate(workspace_id, event_hash):
            return False, "duplicate"

        if self._exceeded_daily_quota(workspace_id, now):
            return False, "daily_quota_exceeded"

        req = PolicyRequest(
            actor_id="scheduler",
            capability_name="notify",
            resource="notification",
            operation="send",
            context="background",
        )
        decision = self._policy.evaluate(req)
        if decision.decision == DecisionType.deny:
            return False, f"policy_denied: {decision.reason}"

        nid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO notifications"
            " (id, workspace_id, event_hash, title, body, decision)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (nid, workspace_id, event_hash, title, body, decision.decision.value),
        )
        self._db.connection.commit()
        return True, nid

    def record_notification(
        self,
        workspace_id: str,
        job_id: str,
        title: str,
        body: str,
        decision: str = "sent",
    ) -> str:
        nid = str(uuid.uuid4())
        event_hash = self._hash_event(title, body)
        self._db.connection.execute(
            "INSERT INTO notifications"
            " (id, workspace_id, job_id, event_hash, title, body, decision)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, workspace_id, job_id, event_hash, title, body, decision),
        )
        self._db.connection.commit()
        return nid

    def record_feedback(
        self, notification_id: str, feedback: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE notifications SET feedback = ?, feedback_at = ? WHERE id = ?",
            (feedback, now, notification_id),
        )
        self._db.connection.commit()

    def set_quiet_hours(
        self,
        workspace_id: str,
        start: str = "",
        end: str = "",
        timezone: str = "UTC",
        max_daily: int = 3,
    ) -> None:
        self._db.connection.execute(
            "INSERT INTO workspace_settings"
            " (workspace_id, quiet_hours_start, quiet_hours_end, timezone, max_daily_notifications)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(workspace_id) DO UPDATE SET"
            " quiet_hours_start = excluded.quiet_hours_start,"
            " quiet_hours_end = excluded.quiet_hours_end,"
            " timezone = excluded.timezone,"
            " max_daily_notifications = excluded.max_daily_notifications",
            (workspace_id, start, end, timezone, max_daily),
        )
        self._db.connection.commit()

    def get_notifications(
        self, workspace_id: str, limit: int = 50
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM notifications WHERE workspace_id = ?"
            " ORDER BY sent_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def _is_quiet_hours(self, workspace_id: str, now: datetime) -> bool:
        cur = self._db.connection.execute(
            "SELECT quiet_hours_start, quiet_hours_end FROM workspace_settings"
            " WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        start: str = row["quiet_hours_start"] or ""
        end: str = row["quiet_hours_end"] or ""
        if not start or not end:
            return False
        current_time = now.strftime("%H:%M")
        if start <= end:
            return start <= current_time <= end
        return current_time >= start or current_time <= end

    def _is_duplicate(self, workspace_id: str, event_hash: str) -> bool:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notifications"
            " WHERE workspace_id = ? AND event_hash = ?",
            (workspace_id, event_hash),
        )
        row = cur.fetchone()
        return row is not None and row["cnt"] > 0

    def _exceeded_daily_quota(self, workspace_id: str, now: datetime) -> bool:
        cur = self._db.connection.execute(
            "SELECT max_daily_notifications FROM workspace_settings"
            " WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        max_daily = row["max_daily_notifications"] if row else 3
        today = now.strftime("%Y-%m-%d")
        cur2 = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notifications"
            " WHERE workspace_id = ? AND sent_at LIKE ?",
            (workspace_id, f"{today}%"),
        )
        row2 = cur2.fetchone()
        count = row2["cnt"] if row2 else 0
        return count >= max_daily

    @staticmethod
    def _hash_event(title: str, body: str) -> str:
        raw = f"{title}|{body}"
        return hashlib.sha256(raw.encode()).hexdigest()
