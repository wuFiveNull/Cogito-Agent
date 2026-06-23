from __future__ import annotations

from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository, AuditRepository, TraceRepository
from cogito_agent.trace import Tracer


class DoctorApplicationService:
    """Diagnostic checks that validate infrastructure components.

    Console doctor views use this service instead of importing
    governance/trace/infrastructure classes directly.
    """

    def __init__(self, db: Database | None = None) -> None:
        self._db = db

    def _get_db(self) -> Database:
        if self._db is not None:
            return self._db
        from cogito_agent.storage import get_db
        return get_db()

    def check_policy_engine(self) -> dict[str, str]:
        """Test PolicyEngine can be instantiated."""
        try:
            PolicyEngine()
            return {"name": "policy_engine", "status": "ok", "message": "available"}
        except Exception:
            return {"name": "policy_engine", "status": "warning", "message": "not available"}

    def check_approval_repo(self) -> dict[str, str]:
        """Test ApprovalRepository can be instantiated."""
        try:
            db = self._get_db()
            ApprovalRepository(db)
            return {"name": "approval_repo", "status": "ok", "message": "available"}
        except Exception:
            return {"name": "approval_repo", "status": "warning", "message": "not available"}

    def check_audit_store(self) -> dict[str, str]:
        """Test AuditLogger can write an audit entry."""
        try:
            db = self._get_db()
            AuditLogger(db)
            return {"name": "audit_store", "status": "ok", "message": "available"}
        except Exception:
            return {"name": "audit_store", "status": "warning", "message": "not available"}

    def check_trace_store(self) -> dict[str, str]:
        """Test Tracer can be instantiated."""
        try:
            db = self._get_db()
            Tracer(db)
            return {"name": "trace_store", "status": "ok", "message": "available"}
        except Exception:
            return {"name": "trace_store", "status": "warning", "message": "not available"}

    def check_recent_audit(self) -> dict[str, str]:
        """Count audit events in the last 24 hours."""
        try:
            from datetime import UTC, datetime, timedelta
            cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
            db = self._get_db()
            count = AuditRepository(db).count_by_time_range(cutoff)
            return {"name": "recent_audit", "status": "ok", "message": f"{count} events in 24h"}
        except Exception:
            return {"name": "recent_audit", "status": "warning", "message": "count unavailable"}

    def check_recent_traces(self) -> dict[str, str]:
        """Count traces in the last 24 hours."""
        try:
            from datetime import UTC, datetime, timedelta
            cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
            db = self._get_db()
            count = TraceRepository(db).count_by_time_range(cutoff)
            return {"name": "recent_traces", "status": "ok", "message": f"{count} traces in 24h"}
        except Exception:
            return {"name": "recent_traces", "status": "warning", "message": "count unavailable"}

    def run_governance_checks(self) -> list[dict[str, str]]:
        """Run all governance-related diagnostic checks."""
        return [
            self.check_policy_engine(),
            self.check_approval_repo(),
            self.check_audit_store(),
            self.check_trace_store(),
            self.check_recent_audit(),
            self.check_recent_traces(),
        ]
