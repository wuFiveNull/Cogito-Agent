from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.shared import DecisionType, PolicyRequest
from cogito_agent.storage import Database

from .decision import DecisionAction, NotificationDecision
from .events import AutonomyEvent, PriorityLevel

_DEFAULT_QUIET_START = "22:00"
_DEFAULT_QUIET_END = "08:00"


class NotificationGate:
    def __init__(
        self,
        db: Database,
        policy_engine: PolicyEngine | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._db = db
        self._policy = policy_engine or PolicyEngine()
        self._audit = audit_logger or AuditLogger(db)

    def _is_quiet_hours(
        self, workspace_id: str, now: datetime,
        config: dict[str, Any] | None = None,
    ) -> bool:
        if config:
            enabled = config.get("quiet_hours_enabled", True)
            if not enabled:
                return False
            start = config.get("quiet_hours_start", _DEFAULT_QUIET_START)
            end = config.get("quiet_hours_end", _DEFAULT_QUIET_END)
        else:
            cur = self._db.connection.execute(
                "SELECT quiet_hours_start, quiet_hours_end FROM workspace_settings"
                " WHERE workspace_id = ?",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            start = row["quiet_hours_start"] or ""
            end = row["quiet_hours_end"] or ""
        start_s = str(start or "")
        end_s = str(end or "")
        if not start_s or not end_s:
            return False
        current_time = now.strftime("%H:%M")
        if start_s <= end_s:
            return start_s <= current_time <= end_s
        return current_time >= start_s or current_time <= end_s

    def _is_duplicate(self, workspace_id: str, dedup_key: str, window_minutes: int = 120) -> bool:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notifications"
            " WHERE workspace_id = ? AND event_hash = ? AND sent_at >= ?",
            (workspace_id, dedup_key, cutoff),
        )
        row = cur.fetchone()
        return row is not None and row["cnt"] > 0

    def _exceeded_daily_quota(self, workspace_id: str, now: datetime, max_daily: int = 5) -> bool:
        if max_daily == 5:
            cur = self._db.connection.execute(
                "SELECT max_daily_notifications FROM workspace_settings"
                " WHERE workspace_id = ?",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row and row["max_daily_notifications"] is not None:
                max_daily = int(row["max_daily_notifications"])
        today = now.strftime("%Y-%m-%d")
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notifications"
            " WHERE workspace_id = ? AND decision = 'push' AND sent_at LIKE ?",
            (workspace_id, f"{today}%"),
        )
        row = cur.fetchone()
        count = row["cnt"] if row else 0
        return count >= max_daily

    def _exceeded_hourly_quota(self, workspace_id: str, now: datetime, max_hourly: int = 2) -> bool:
        hour_start = now.strftime("%Y-%m-%dT%H:00:00")
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notifications"
            " WHERE workspace_id = ? AND decision = 'push' AND sent_at >= ?",
            (workspace_id, hour_start),
        )
        row = cur.fetchone()
        count = row["cnt"] if row else 0
        return count >= max_hourly

    def _compute_cost_score(
        self,
        event: AutonomyEvent,
        quiet_hours_hit: bool,
        quota_hit: bool,
        recent_feedback: list[str] | None = None,
    ) -> float:
        score = 0.0
        if event.priority == PriorityLevel.low:
            score += 3.0
        elif event.priority == PriorityLevel.normal:
            score += 2.0
        elif event.priority == PriorityLevel.high:
            score += 0.5
        elif event.priority == PriorityLevel.urgent:
            score += 0.0
        if quiet_hours_hit:
            score += 5.0
        if quota_hit:
            score += 3.0
        if recent_feedback:
            for fb in recent_feedback:
                if fb == "too_many":
                    score += 2.0
                elif fb == "wrong_time":
                    score += 1.5
                elif fb == "not_useful":
                    score += 1.0
        return score

    def _governance_check(self, event: AutonomyEvent) -> tuple[bool, str, bool]:
        actor_id = event.source or "proactive_loop"
        req = PolicyRequest(
            actor_id=actor_id,
            capability_name="notification.send",
            resource=f"workspace/{event.workspace_id}",
            operation="send",
            context="background",
        )
        decision = self._policy.evaluate(req)
        if decision.decision == DecisionType.deny:
            return False, "governance_denied", False
        if decision.decision == DecisionType.require_approval:
            return False, "governance_requires_approval", True
        return True, "governance_allowed", False

    def evaluate(
        self,
        event: AutonomyEvent,
        config: dict[str, Any] | None = None,
    ) -> NotificationDecision:
        cfg = config or {}
        now = datetime.now(UTC)
        dedup_key = event.build_dedup_key()
        workspace_id = event.workspace_id

        qh_enabled = cfg.get("quiet_hours_enabled", True)
        urgent_bypass_qh = cfg.get("urgent_bypass_quiet_hours", True)
        quiet_hours_hit = False
        if qh_enabled and not (event.quiet_hours_override or
                                (event.priority == PriorityLevel.urgent and urgent_bypass_qh)):
            quiet_hours_hit = self._is_quiet_hours(workspace_id, now, cfg)

        daily_max = int(cfg.get("daily_quota", 5))
        hourly_max = int(cfg.get("hourly_quota", 2))
        urgent_bypass_quota = cfg.get("urgent_bypass_quota", True)
        quota_hit = False
        if not (event.priority == PriorityLevel.urgent and urgent_bypass_quota):
            if self._exceeded_daily_quota(workspace_id, now, daily_max):
                quota_hit = True
            elif self._exceeded_hourly_quota(workspace_id, now, hourly_max):
                quota_hit = True

        dedup_window = int(cfg.get("dedup_window_minutes", 120))
        dedup_hit = self._is_duplicate(workspace_id, dedup_key, dedup_window)

        recent_feedback: list[str] = []
        try:
            cur = self._db.connection.execute(
                "SELECT feedback FROM notifications"
                " WHERE workspace_id = ? AND feedback IS NOT NULL"
                " ORDER BY sent_at DESC LIMIT 5",
                (workspace_id,),
            )
            recent_feedback = [r["feedback"] for r in cur.fetchall() if r["feedback"]]
        except Exception:
            pass

        cost_score = self._compute_cost_score(event, quiet_hours_hit, quota_hit, recent_feedback)

        priority_score = {"low": 1.0, "normal": 2.0, "high": 3.0, "urgent": 4.0}.get(
            event.priority.value, 2.0
        )

        decision = NotificationDecision(
            event_id=event.event_id,
            action=DecisionAction.push,
            cost_score=cost_score,
            priority_score=priority_score,
            dedup_hit=dedup_hit,
            quiet_hours_hit=quiet_hours_hit,
            quota_hit=quota_hit,
            workspace_id=workspace_id,
            user_id=event.user_id,
            trace_id=event.trace_id,
        )

        if quiet_hours_hit:
            decision.action = DecisionAction.skip
            decision.reason_code = "quiet_hours"
            decision.reason = "Quiet hours active"
            return decision

        if dedup_hit:
            decision.action = DecisionAction.skip
            decision.reason_code = "dedup"
            decision.reason = "Duplicate event within dedup window"
            return decision

        if quota_hit:
            if cost_score < 5.0:
                decision.action = DecisionAction.defer
                decision.reason_code = "quota_deferred"
                decision.reason = "Daily/hourly quota exceeded, deferred"
            else:
                decision.action = DecisionAction.push
                decision.reason_code = "quota_exceeded_high_priority"
                decision.reason = "Quota exceeded but high cost/priority bypasses"
            return decision

        governance_ok, gov_reason, requires_approval = self._governance_check(event)
        if not governance_ok:
            if requires_approval:
                decision.action = DecisionAction.require_approval
                decision.reason_code = "requires_approval"
                decision.reason = gov_reason
                decision.requires_approval = True
            else:
                decision.action = DecisionAction.skip
                decision.reason_code = "governance_denied"
                decision.reason = gov_reason
            return decision

        decision.action = DecisionAction.push
        decision.reason_code = "allowed"
        decision.reason = "All checks passed"
        return decision

    def persist_decision(self, decision: NotificationDecision) -> str:
        did = decision.decision_id
        self._db.connection.execute(
            "INSERT INTO notification_decisions"
            " (id, event_id, workspace_id, user_id, action, reason_code, reason,"
            " cost_score, priority_score, dedup_hit, quiet_hours_hit, quota_hit,"
            " requires_approval, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                did, decision.event_id, decision.workspace_id, decision.user_id,
                decision.action.value, decision.reason_code, decision.reason,
                decision.cost_score, decision.priority_score,
                int(decision.dedup_hit), int(decision.quiet_hours_hit),
                int(decision.quota_hit), int(decision.requires_approval),
                decision.trace_id, decision.created_at.isoformat(),
            ),
        )
        self._db.connection.commit()
        return did

    def record_feedback(
        self, notification_id: str, feedback: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE notifications SET feedback = ?, feedback_at = ? WHERE id = ?",
            (feedback, now, notification_id),
        )
        self._db.connection.commit()

    def record_notification(
        self,
        workspace_id: str,
        title: str,
        body: str,
        decision: str = "push",
        priority: str = "normal",
        dedup_key: str = "",
        trace_id: str = "",
    ) -> str:
        nid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO notifications"
            " (id, workspace_id, event_hash, title, body, decision, priority, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (nid, workspace_id, dedup_key or "", title, body, decision, priority,
             datetime.now(UTC).isoformat()),
        )
        self._db.connection.commit()
        return nid

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

    def should_notify(
        self,
        workspace_id: str,
        title: str,
        body: str,
        priority: str = "normal",
    ) -> tuple[bool, str]:
        from .events import AutonomyEvent, PriorityLevel
        try:
            pl = PriorityLevel(priority)
        except ValueError:
            pl = PriorityLevel.normal
        event = AutonomyEvent(title=title, body=body, workspace_id=workspace_id, priority=pl)
        decision = self.evaluate(event)
        self.persist_decision(decision)
        if decision.action == DecisionAction.push:
            nid = self.record_notification(
                workspace_id=workspace_id, title=title, body=body,
                decision="push", priority=priority,
                dedup_key=event.build_dedup_key(),
            )
            return True, nid
        reason_map = {
            "dedup": "duplicate",
            "quiet_hours": "quiet_hours",
            "quota_deferred": "daily_quota_exceeded",
            "quota_exceeded_high_priority": "daily_quota_exceeded",
            "governance_denied": "governance_denied",
            "governance_requires_approval": "governance_requires_approval",
            "requires_approval": "governance_requires_approval",
        }
        return False, reason_map.get(decision.reason_code, decision.reason_code)

    def try_notify_or_inbox(
        self,
        workspace_id: str,
        title: str,
        body: str,
        priority: str = "normal",
        trace_id: str = "",
    ) -> tuple[str, str]:
        allowed, result = self.should_notify(
            workspace_id, title, body, priority=priority,
        )
        if allowed:
            return ("notified", result)
        iid = self.write_inbox(
            workspace_id, title, body,
            source="system", priority=priority, trace_id=trace_id,
        )
        return ("inbox", iid)

    def list_inbox(self, workspace_id: str = "*", limit: int = 50) -> list[dict[str, Any]]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM inbox_items ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM inbox_items WHERE workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def read_inbox_item(self, item_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM inbox_items WHERE id = ?", (item_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def mark_inbox_read(self, item_id: str) -> None:
        self._db.connection.execute(
            "UPDATE inbox_items SET read_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), item_id),
        )
        self._db.connection.commit()

    def clear_inbox(self, workspace_id: str = "*") -> None:
        if workspace_id == "*":
            self._db.connection.execute("DELETE FROM inbox_items")
        else:
            self._db.connection.execute(
                "DELETE FROM inbox_items WHERE workspace_id = ?", (workspace_id,)
            )
        self._db.connection.commit()

    def write_inbox(
        self,
        workspace_id: str,
        title: str,
        body: str,
        source: str = "system",
        priority: str = "normal",
        trace_id: str = "",
    ) -> str:
        iid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO inbox_items"
            " (id, workspace_id, title, body, source, priority, trace_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (iid, workspace_id, title, body, source, priority, trace_id or None),
        )
        self._db.connection.commit()
        return iid

    def list_decisions(
        self, workspace_id: str = "*", limit: int = 50
    ) -> list[dict[str, Any]]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM notification_decisions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM notification_decisions WHERE workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def count_push_recent(self, workspace_id: str, minutes: int = 60) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notification_decisions"
            " WHERE workspace_id = ? AND action = 'push' AND created_at >= ?",
            (workspace_id, cutoff),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def get_notifications(
        self, workspace_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        cur = self._db.connection.execute(
            "SELECT * FROM notifications WHERE workspace_id = ?"
            " ORDER BY sent_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
