"""SystemReader — 系统状态、DB 统计、配置信息的只读查询。"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from cogito_agent.storage import Database
from cogito_agent.version import APP_VERSION


class SystemReader:
    """系统状态、数据库统计和配置的只读查询。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── DB info ────────────────────────────────────────────────────────────

    def db_info(self) -> dict[str, object]:
        try:
            ver = self._db.current_version()
            path = os.environ.get("COGITO_DB_PATH", ":memory:")
            return {"ok": True, "path": path, "migration_version": ver}
        except Exception as exc:
            return {"ok": False, "path": "", "error": str(exc)}

    def db_table_count(self, table: str) -> int:
        """安全获取表行数（白名单检查）。"""
        allowed = {
            "memories", "memory_items", "approval_records",
            "outbox_messages", "notification_decisions",
            "audit_logs", "traces", "spans", "sessions",
            "messages", "drift_runs", "drift_state",
        }
        if table not in allowed:
            return 0
        try:
            row = self._db.connection.execute(
                f"SELECT COUNT(*) AS cnt FROM {table}"
            ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def db_table_count_where(
        self, table: str, where: str, params: tuple[object, ...] = ()
    ) -> int:
        allowed = {
            "memories", "memory_items", "approval_records",
            "outbox_messages", "notification_decisions",
            "audit_logs", "traces",
        }
        if table not in allowed:
            return 0
        try:
            row = self._db.connection.execute(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE {where}", params
            ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0

    # ── Config info ────────────────────────────────────────────────────────

    def config(self) -> dict[str, str]:
        """返回 CLI config_manager 的平面配置。"""
        try:
            from cogito_agent.cli.config_manager import get_config
            cfg = get_config()
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    def model_info(self) -> dict[str, object]:
        cfg = self.config()
        return {
            "provider": cfg.get("model.provider", "mock"),
            "streaming_enabled": cfg.get("model.streaming_enabled", "true").lower() == "true",
            "timeout_seconds": int(cfg.get("model.timeout_seconds", "60")),
        }

    def secrets_info(self) -> dict[str, object]:
        cfg = self.config()
        backend = cfg.get("secrets.backend", "local")
        available = False
        try:
            from cogito_agent.security import get_provider_from_config
            provider = get_provider_from_config(cfg)
            keys = provider.list_keys()
            available = len(keys) > 0
        except Exception:
            pass
        return {"backend": backend, "available": available}

    # ── Full status ────────────────────────────────────────────────────────

    def build_status(self) -> dict[str, object]:
        """兼容现有的 build_status() 输出。"""
        db = self.db_info()
        model = self.model_info()
        secrets = self.secrets_info()

        now = datetime.now(UTC)
        since_24h = (now - timedelta(hours=24)).isoformat()

        return {
            "version": os.environ.get("COGITO_CONSOLE_VERSION", APP_VERSION),
            "db": db,
            "model": model,
            "secrets": secrets,
            "counts": {
                "memories": self.db_table_count("memories"),
                "memory_candidates_pending": self._pending_candidates_count(),
                "approvals_pending": self.db_table_count_where(
                    "approval_records", "status = 'pending'"
                ),
                "autonomy_outbox_pending": self.db_table_count_where(
                    "outbox_messages", "status = 'pending'"
                ),
                "autonomy_decisions_24h": self.db_table_count_where(
                    "notification_decisions", "created_at >= ?", (since_24h,)
                ),
                "audit_events_24h": self.db_table_count_where(
                    "audit_logs", "created_at >= ?", (since_24h,)
                ),
                "traces_24h": self.db_table_count_where(
                    "traces", "started_at >= ?", (since_24h,)
                ),
            },
            "limitations": [
                "No real Telegram/Feishu delivery for outbox",
                "Config viewer is read-only (no editing)",
                "Live provider check not available in console doctor",
            ],
        }

    def _pending_candidates_count(self) -> int:
        try:
            row = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM memory_items"
                " WHERE workspace_id = 'default' AND status = 'active'"
            ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0

    # ── Usage snapshot ─────────────────────────────────────────────────────

    def usage_snapshot(
        self, workspace_id: str = "default"
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        cutoff_24h = (now - timedelta(hours=24)).isoformat()
        cutoff_7d = (now - timedelta(days=7)).isoformat()

        from .trace_reader import TraceReader
        tr = TraceReader(self._db)

        model_calls_24h = tr.count_model_calls(cutoff_24h, workspace_id)
        model_calls_7d = tr.count_model_calls(cutoff_7d, workspace_id)
        avg_latency_24h = tr.avg_model_latency(cutoff_24h, workspace_id)
        tool_calls_24h = tr.count_tool_calls(cutoff_24h, workspace_id)
        tool_calls_7d = tr.count_tool_calls(cutoff_7d, workspace_id)
        total_traces_24h = tr.count_traces(cutoff_24h, workspace_id)
        total_traces_7d = tr.count_traces(cutoff_7d, workspace_id)
        failed_24h = tr.count_traces(cutoff_24h, workspace_id, failed_only=True)
        failure_rate_24h = (
            round(failed_24h / total_traces_24h * 100, 1)
            if total_traces_24h > 0
            else 0.0
        )
        decisions_24h = self.db_table_count_where(
            "notification_decisions",
            "created_at >= ?", (cutoff_24h,),
        )

        return {
            "model_calls_24h": model_calls_24h,
            "model_calls_7d": model_calls_7d,
            "tool_calls_24h": tool_calls_24h,
            "tool_calls_7d": tool_calls_7d,
            "avg_latency_24h": avg_latency_24h,
            "failure_rate_24h": failure_rate_24h,
            "total_traces_24h": total_traces_24h,
            "total_traces_7d": total_traces_7d,
            "decisions_24h": decisions_24h,
        }
