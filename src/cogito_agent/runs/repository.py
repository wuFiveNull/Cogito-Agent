from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from cogito_agent.storage import Database
from cogito_agent.trace.redaction import RedactionHelper

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "abandoned"}


class RunRepository:
    """SQLite-backed durable lifecycle for local background work."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._redactor = RedactionHelper()

    def create(
        self,
        *,
        run_type: str,
        workspace_id: str,
        definition_id: str = "",
        parent_run_id: str | None = None,
        idempotency_key: str = "",
        scheduled_at: str | None = None,
        priority: str = "normal",
        max_attempts: int = 1,
        input_data: dict[str, object] | None = None,
    ) -> dict[str, object]:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        payload = self._redactor.redact(json.dumps(input_data or {}, default=str))
        try:
            with self._db.connection:
                self._db.connection.execute(
                    "INSERT INTO runs"
                    " (id, run_type, definition_id, parent_run_id, workspace_id, status,"
                    " priority, idempotency_key, scheduled_at, max_attempts, input_json,"
                    " created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        run_type,
                        definition_id,
                        parent_run_id,
                        workspace_id,
                        priority,
                        idempotency_key,
                        scheduled_at,
                        max_attempts,
                        payload,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            if not idempotency_key:
                raise
            existing = self.get_by_idempotency(run_type, idempotency_key)
            if existing is None:
                raise
            return existing
        self.append_event(run_id, "created", {"scheduled_at": scheduled_at or ""})
        result = self.get(run_id)
        if result is None:
            raise RuntimeError("Created run could not be loaded")
        return result

    def claim(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> bool:
        now = datetime.now(UTC)
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET status='running', claimed_by=?, lease_expires_at=?,"
                " heartbeat_at=?, started_at=COALESCE(started_at, ?),"
                " attempt_count=attempt_count+1"
                " WHERE id=? AND status IN ('pending', 'abandoned')"
                " AND attempt_count < max_attempts",
                (
                    worker_id,
                    (now + timedelta(seconds=lease_seconds)).isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                    run_id,
                ),
            )
        if cursor.rowcount == 1:
            self.append_event(run_id, "claimed", {"worker_id": worker_id})
            return True
        return False

    def heartbeat(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> bool:
        now = datetime.now(UTC)
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET heartbeat_at=?, lease_expires_at=?"
                " WHERE id=? AND status='running' AND claimed_by=?",
                (
                    now.isoformat(),
                    (now + timedelta(seconds=lease_seconds)).isoformat(),
                    run_id,
                    worker_id,
                ),
            )
        return cursor.rowcount == 1

    def pause_for_approval(self, run_id: str, approval_id: str) -> bool:
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET status='waiting_approval', lease_expires_at=NULL"
                " WHERE id=? AND status='running'",
                (run_id,),
            )
        if cursor.rowcount == 1:
            self.append_event(
                run_id,
                "waiting_approval",
                {"approval_id": approval_id},
            )
            return True
        return False

    def resume_waiting(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> bool:
        now = datetime.now(UTC)
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET status='running', claimed_by=?, heartbeat_at=?,"
                " lease_expires_at=?, attempt_count=attempt_count+1"
                " WHERE id=? AND status='waiting_approval'",
                (
                    worker_id,
                    now.isoformat(),
                    (now + timedelta(seconds=lease_seconds)).isoformat(),
                    run_id,
                ),
            )
        if cursor.rowcount == 1:
            self.append_event(run_id, "resumed", {"worker_id": worker_id})
            return True
        return False

    def set_trace_id(self, run_id: str, trace_id: str) -> None:
        with self._db.connection:
            self._db.connection.execute("UPDATE runs SET trace_id=? WHERE id=?", (trace_id, run_id))

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        result_data: dict[str, object] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> bool:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"Invalid terminal run status: {status}")
        result_json = self._redactor.redact(json.dumps(result_data or {}, default=str))
        safe_error = self._redactor.redact(error_message)
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET status=?, result_json=?, error_code=?, error_message=?,"
                " finished_at=?, lease_expires_at=NULL"
                " WHERE id=? AND status IN"
                " ('running', 'pending', 'abandoned', 'waiting_approval')",
                (
                    status,
                    result_json,
                    error_code,
                    safe_error,
                    datetime.now(UTC).isoformat(),
                    run_id,
                ),
            )
        if cursor.rowcount == 1:
            self.append_event(
                run_id,
                "finished",
                {"status": status, "error_code": error_code},
            )
            return True
        return False

    def cancel(self, run_id: str, *, reason: str = "cancelled by user") -> bool:
        safe_reason = self._redactor.redact(reason)
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET status='cancelled', error_code='cancelled',"
                " error_message=?, finished_at=?, lease_expires_at=NULL"
                " WHERE id=? AND status NOT IN ('succeeded','failed','cancelled')",
                (safe_reason, datetime.now(UTC).isoformat(), run_id),
            )
        if cursor.rowcount == 1:
            self.append_event(run_id, "cancelled", {"reason": safe_reason})
            return True
        return False

    def retry(self, run_id: str) -> bool:
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE runs SET status='pending', claimed_by=NULL,"
                " lease_expires_at=NULL, heartbeat_at=NULL, finished_at=NULL,"
                " error_code='', error_message='',"
                " max_attempts=CASE WHEN max_attempts <= attempt_count"
                " THEN attempt_count + 1 ELSE max_attempts END"
                " WHERE id=? AND status IN ('failed','cancelled','abandoned')",
                (run_id,),
            )
        if cursor.rowcount == 1:
            self.append_event(run_id, "retry_requested", {})
            return True
        return False

    def abandon_expired(
        self,
        *,
        now: datetime | None = None,
        run_type: str | None = None,
    ) -> list[dict[str, object]]:
        current = (now or datetime.now(UTC)).isoformat()
        sql = (
            "SELECT * FROM runs WHERE status='running'"
            " AND lease_expires_at IS NOT NULL AND lease_expires_at < ?"
        )
        params: list[object] = [current]
        if run_type is not None:
            sql += " AND run_type=?"
            params.append(run_type)
        rows = self._db.connection.execute(sql, params).fetchall()
        abandoned = [dict(row) for row in rows]
        if not abandoned:
            return []
        with self._db.connection:
            self._db.connection.executemany(
                "UPDATE runs SET status='abandoned', finished_at=?, lease_expires_at=NULL"
                " WHERE id=? AND status='running'",
                [(current, str(row["id"])) for row in abandoned],
            )
        for row in abandoned:
            self.append_event(str(row["id"]), "lease_expired", {})
        return abandoned

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> str:
        event_id = str(uuid.uuid4())
        redacted = self._redactor.redact(json.dumps(payload, default=str))
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO run_events"
                " (id, run_id, sequence, event_type, payload_json, created_at)"
                " SELECT ?, ?, COALESCE(MAX(sequence), 0) + 1, ?, ?, ?"
                " FROM run_events WHERE run_id=?",
                (
                    event_id,
                    run_id,
                    event_type,
                    redacted,
                    datetime.now(UTC).isoformat(),
                    run_id,
                ),
            )
        return event_id

    def add_output(self, run_id: str, output_type: str, reference_id: str) -> str:
        existing = self._db.connection.execute(
            "SELECT id FROM run_outputs WHERE run_id=? AND output_type=? AND reference_id=?",
            (run_id, output_type, reference_id),
        ).fetchone()
        if existing:
            return str(existing["id"])
        output_id = str(uuid.uuid4())
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO run_outputs (id, run_id, output_type, reference_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    output_id,
                    run_id,
                    output_type,
                    reference_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return output_id

    def get(self, run_id: str) -> dict[str, object] | None:
        row = self._db.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_by_idempotency(self, run_type: str, idempotency_key: str) -> dict[str, object] | None:
        row = self._db.connection.execute(
            "SELECT * FROM runs WHERE run_type=? AND idempotency_key=?",
            (run_type, idempotency_key),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(
        self,
        *,
        workspace_id: str | None = None,
        status: str | None = None,
        run_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        sql = "SELECT * FROM runs WHERE 1=1"
        params: list[object] = []
        if workspace_id:
            sql += " AND workspace_id=?"
            params.append(workspace_id)
        if status:
            sql += " AND status=?"
            params.append(status)
        if run_type:
            sql += " AND run_type=?"
            params.append(run_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = self._db.connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str) -> list[dict[str, object]]:
        rows = self._db.connection.execute(
            "SELECT * FROM run_events WHERE run_id=? ORDER BY sequence", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_outputs(self, run_id: str) -> list[dict[str, object]]:
        rows = self._db.connection.execute(
            "SELECT * FROM run_outputs WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
