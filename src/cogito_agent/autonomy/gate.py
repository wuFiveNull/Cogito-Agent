from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.models import ModelAdapter
from cogito_agent.shared import DecisionType, PolicyRequest
from cogito_agent.storage import Database

from .decision import DecisionAction, NotificationDecision
from .events import AutonomyEvent, PriorityLevel

_DEFAULT_QUIET_START = "22:00"
_DEFAULT_QUIET_END = "08:00"

_JUDGE_SYSTEM_PROMPT = (
    "你是消息推送价值评估代理。你需要根据以下3个维度对一条消息打分（1-5分），"
    "判断它是否值得主动推送给用户。\n\n"
    "评分规则：\n"
    "1 = 完全不符合  2 = 较多不符合  3 = 中立  4 = 较多符合  5 = 完全符合\n\n"
    "维度说明：\n"
    "- information_gap（信息差）：用户大概率不知道这条信息中的关键内容吗？\n"
    "- relevance（相关性）：这条信息与用户当前关心的事情/所处场景相关吗？\n"
    "- expected_impact（预期影响）：这条信息如果推送，对用户有实质帮助/价值吗？\n\n"
    "只返回合法 JSON，不要 markdown 代码块。"
)


class NotificationGate:
    def __init__(
        self,
        db: Database,
        policy_engine: PolicyEngine | None = None,
        audit_logger: AuditLogger | None = None,
        llm_adapter: ModelAdapter | None = None,
    ) -> None:
        self._db = db
        self._policy = policy_engine or PolicyEngine()
        self._audit = audit_logger or AuditLogger(db)
        self._llm = llm_adapter

    def set_llm_adapter(self, llm_adapter: ModelAdapter | None) -> None:
        """Inject a light LLM adapter for judge evaluation."""
        self._llm = llm_adapter

    def _is_quiet_hours(
        self,
        workspace_id: str,
        now: datetime,
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
                "SELECT max_daily_notifications FROM workspace_settings WHERE workspace_id = ?",
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

    # ── LLM Judge ────────────────────────────────────────────────────────

    @staticmethod
    def _build_judge_prompt(
        title: str,
        body: str,
        priority: str,
        recent_notifications: list[str],
    ) -> list[dict[str, str]]:
        """Build messages for the judge LLM.

        Returns a two-turn chat (system + user) that asks the LLM to rate
        the notification on 3 dimensions (1-5 scale).
        """
        recent_block = "\n".join(
            f"- {n[:80]}" for n in recent_notifications[-5:]
        ) if recent_notifications else "（无近期推送）"
        user_text = (
            f"## 待评估消息\n"
            f"标题：{title}\n"
            f"内容：{body or '（无正文）'}\n"
            f"优先级：{priority}\n\n"
            f"## 近期已推送消息\n{recent_block}\n\n"
            f"---\n"
            f"只输出 JSON，格式：\n"
            f'{{"information_gap": 3, "relevance": 3, "expected_impact": 3}}'
        )
        return [
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

    def _judge_llm_dims(
        self,
        event: AutonomyEvent,
    ) -> dict[str, int] | None:
        """Call the light LLM to rate this notification on 3 dimensions (1-5).

        Returns None if the LLM is unavailable or the call fails (fail-open).
        """
        if not self._llm:
            return None
        recent_fb: list[str] = []
        try:
            cur = self._db.connection.execute(
                "SELECT title FROM notifications"
                " WHERE workspace_id = ? AND decision = 'push'"
                " ORDER BY sent_at DESC LIMIT 5",
                (event.workspace_id,),
            )
            recent_fb = [str(r["title"]) for r in cur.fetchall() if r["title"]]
        except Exception:
            pass
        messages = self._build_judge_prompt(
            title=event.title,
            body=event.body,
            priority=event.priority.value,
            recent_notifications=recent_fb,
        )
        try:
            resp = self._llm.chat(messages)
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0]
            parsed = json.loads(raw)
            return {
                "information_gap": max(1, min(5, int(parsed.get("information_gap", 3)))),
                "relevance": max(1, min(5, int(parsed.get("relevance", 3)))),
                "expected_impact": max(1, min(5, int(parsed.get("expected_impact", 3)))),
            }
        except Exception:
            return None  # fail-open: LLM unavailable → skip LLM judgment

    @staticmethod
    def _compute_judge_final_score(
        *,
        age_hours: float,
        sent_24h: int,
        interrupt_factor: float,
        llm_dims: dict[str, int] | None,
        cfg: dict[str, Any],
    ) -> tuple[float, dict[str, float], dict[str, int] | None]:
        """Akashic-style two-tier scoring: deterministic dims + LLM dims."""
        # Deterministic dims
        daily_max = max(1, int(cfg.get("judge_daily_max", 8)))
        urgency_horizon = max(1.0, float(cfg.get("judge_urgency_horizon_hours", 12.0)))
        urgency = max(0.0, 1.0 - (max(age_hours, 0.0) / urgency_horizon))
        balance = max(0.0, 1.0 - (max(sent_24h, 0) / float(daily_max)))
        dynamics = 0.6 + 0.4 * max(0.0, min(1.0, float(interrupt_factor)))
        deterministic = {"urgency": urgency, "balance": balance, "dynamics": dynamics}

        # Balance veto
        veto_balance_min = float(cfg.get("judge_veto_balance_min", 0.1))
        if balance < veto_balance_min:
            return 0.0, deterministic, None

        # LLM dims with veto
        llm_dims_norm: dict[str, float] = {}
        if llm_dims:
            veto_dim_min = int(cfg.get("judge_veto_llm_dim_min", 2))
            for key in ("information_gap", "relevance", "expected_impact"):
                raw = llm_dims.get(key, 3)
                if raw < veto_dim_min:
                    return 0.0, deterministic, llm_dims
                llm_dims_norm[key] = (raw - 1) / 4.0  # [1,5] → [0,1]

        # Weighted blend
        weights = {
            "urgency": float(cfg.get("judge_weight_urgency", 0.15)),
            "balance": float(cfg.get("judge_weight_balance", 0.10)),
            "dynamics": float(cfg.get("judge_weight_dynamics", 0.10)),
            "information_gap": float(cfg.get("judge_weight_information_gap", 0.25)),
            "relevance": float(cfg.get("judge_weight_relevance", 0.20)),
            "expected_impact": float(cfg.get("judge_weight_expected_impact", 0.20)),
        }
        dims = dict(deterministic)
        dims.update(llm_dims_norm)
        weight_sum = sum(weights.get(k, 0.0) for k in dims)
        if weight_sum <= 0:
            return 0.0, deterministic, llm_dims
        final = sum(weights.get(k, 0.0) * dims[k] for k in dims) / weight_sum
        return final, deterministic, llm_dims

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

        if event.is_expired(now):
            return NotificationDecision(
                event_id=event.event_id,
                action=DecisionAction.skip,
                reason_code="expired",
                reason="Event expired before evaluation",
                workspace_id=workspace_id,
                user_id=event.user_id,
                trace_id=event.trace_id,
            )

        qh_enabled = cfg.get("quiet_hours_enabled", True)
        urgent_bypass_qh = cfg.get("urgent_bypass_quiet_hours", True)
        quiet_hours_hit = False
        if qh_enabled and not (
            event.quiet_hours_override
            or (event.priority == PriorityLevel.urgent and urgent_bypass_qh)
        ):
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

        # ── LLM Judge: evaluate semantic value of the notification ──
        llm_dims = self._judge_llm_dims(event)
        decision.llm_dimensions = llm_dims or {}

        # Compute judge dims: age_hours, sent_24h, interrupt_factor
        age_hours = 0.0
        if event.created_at:
            age_hours = max(0.0, (now - event.created_at).total_seconds() / 3600.0)
        sent_24h = 0
        try:
            cutoff_24h = (now - timedelta(hours=24)).isoformat()
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM notifications"
                " WHERE workspace_id = ? AND decision = 'push' AND sent_at >= ?",
                (workspace_id, cutoff_24h),
            )
            row = cur.fetchone()
            sent_24h = row["cnt"] if row else 0
        except Exception:
            pass
        interrupt_factor = float(event.priority.value in ("high", "urgent"))

        judge_score, deterministic_dims, _ = self._compute_judge_final_score(
            age_hours=age_hours,
            sent_24h=sent_24h,
            interrupt_factor=interrupt_factor,
            llm_dims=llm_dims,
            cfg=cfg,
        )

        # Balance veto (deterministic: too many sent recently)
        if judge_score == 0.0 and deterministic_dims.get("balance", 1.0) < float(
            cfg.get("judge_veto_balance_min", 0.1)
        ):
            decision.action = DecisionAction.skip
            decision.reason_code = "balance_veto"
            decision.reason = "Too many notifications sent recently (balance veto)"
            return decision

        # LLM dim veto (any dimension too low)
        if judge_score == 0.0 and llm_dims is not None:
            min_dim = int(cfg.get("judge_veto_llm_dim_min", 2))
            low_dims = [k for k, v in llm_dims.items() if v < min_dim]
            if low_dims:
                decision.action = DecisionAction.skip
                decision.reason_code = "llm_veto"
                decision.reason = f"LLM judged insufficient: {', '.join(low_dims)}"
                return decision

        # Score threshold
        send_threshold = float(cfg.get("judge_send_threshold", 0.60))
        if judge_score < send_threshold:
            decision.action = DecisionAction.skip
            decision.reason_code = "below_threshold"
            decision.reason = f"Judge score {judge_score:.3f} below threshold {send_threshold}"
            return decision

        decision.action = DecisionAction.push
        decision.reason_code = "allowed"
        decision.reason = "Judge approved"
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
                did,
                decision.event_id,
                decision.workspace_id,
                decision.user_id,
                decision.action.value,
                decision.reason_code,
                decision.reason,
                decision.cost_score,
                decision.priority_score,
                int(decision.dedup_hit),
                int(decision.quiet_hours_hit),
                int(decision.quota_hit),
                int(decision.requires_approval),
                decision.trace_id,
                decision.created_at.isoformat(),
            ),
        )
        self._db.connection.commit()
        return did

    def record_feedback(self, notification_id: str, feedback: str) -> None:
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
        commit: bool = True,
    ) -> str:
        nid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO notifications"
            " (id, workspace_id, event_hash, title, body, decision, priority, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                nid,
                workspace_id,
                dedup_key or "",
                title,
                body,
                decision,
                priority,
                datetime.now(UTC).isoformat(),
            ),
        )
        if commit:
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
                workspace_id=workspace_id,
                title=title,
                body=body,
                decision="push",
                priority=priority,
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
            workspace_id,
            title,
            body,
            priority=priority,
        )
        if allowed:
            return ("notified", result)
        iid = self.write_inbox(
            workspace_id,
            title,
            body,
            source="system",
            priority=priority,
            trace_id=trace_id,
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
                "SELECT * FROM inbox_items WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def read_inbox_item(self, item_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute("SELECT * FROM inbox_items WHERE id = ?", (item_id,))
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

    def list_decisions(self, workspace_id: str = "*", limit: int = 50) -> list[dict[str, Any]]:
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

    def get_notifications(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        cur = self._db.connection.execute(
            "SELECT * FROM notifications WHERE workspace_id = ? ORDER BY sent_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
