from __future__ import annotations

import json
import uuid
from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MessageRepository, SessionRepository
from cogito_agent.trace.redaction import RedactionHelper

from ..markdown import render_safe_markdown


class ChatWorkspaceService:
    """Workspace-scoped application boundary for Console chat operations."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._sessions = SessionRepository(db)
        self._messages = MessageRepository(db)
        self._audit = AuditLogger(db)
        self._redactor = RedactionHelper()

    def list_sessions(
        self, workspace_id: str, *, page: int = 1, page_size: int = 30
    ) -> dict[str, object]:
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        all_sessions = self._sessions.list_by_workspace(workspace_id)
        start = (page - 1) * page_size
        selected = all_sessions[start : start + page_size]
        items: list[dict[str, object]] = []
        for session in selected:
            sid = str(session["id"])
            messages = self._messages.list_by_session(sid, workspace_id)
            last = messages[-1] if messages else None
            items.append(
                {
                    "id": sid,
                    "title": self._redactor.redact(str(session.get("title", ""))),
                    "created_at": str(session.get("created_at", "")),
                    "updated_at": str(session.get("updated_at", "")),
                    "message_count": len(messages),
                    "last_preview": self._redactor.redact(
                        str(last.get("content", ""))[:60] if last else ""
                    ),
                }
            )
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "has_more": start + page_size < len(all_sessions),
        }

    def get_messages(
        self, workspace_id: str, session_id: str, *, page: int = 1, page_size: int = 40
    ) -> dict[str, object] | None:
        session = self._sessions.get_by_id(session_id, workspace_id)
        if session is None:
            return None
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        all_messages = self._messages.list_by_session(session_id, workspace_id)
        end = len(all_messages) - (page - 1) * page_size
        start = max(0, end - page_size)
        selected = all_messages[start : max(0, end)] if end > 0 else []
        messages: list[dict[str, object]] = []
        for message in selected:
            metadata = self._parse_json(str(message.get("metadata_json", "{}")))
            raw_content = str(message.get("content", ""))
            messages.append(
                {
                    "id": str(message["id"]),
                    "role": str(message["role"]),
                    "content": self._redactor.redact(raw_content),
                    "content_html": render_safe_markdown(raw_content),
                    "created_at": str(message.get("created_at", "")),
                    "trace_id": self._redactor.redact(str(metadata.get("trace_id", ""))),
                }
            )
        return {
            "session": session,
            "messages": messages,
            "page": page,
            "has_older": start > 0,
            "last_user_message": next(
                (
                    self._redactor.redact(str(item.get("content", "")))
                    for item in reversed(all_messages)
                    if str(item.get("role", "")) == "user"
                ),
                "",
            ),
        }

    def rename_session(
        self, workspace_id: str, session_id: str, title: str, actor_id: str = "user"
    ) -> dict[str, object] | None:
        session = self._sessions.get_by_id(session_id, workspace_id)
        clean_title = " ".join(title.split())[:80]
        if session is None or not clean_title:
            return None
        before = str(session.get("title", ""))
        self._db.connection.execute(
            "UPDATE sessions SET title = ?, updated_at = datetime('now') "
            "WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (clean_title, session_id, workspace_id),
        )
        self._db.connection.commit()
        self._audit.log(
            actor_id=actor_id,
            action="session_renamed",
            resource="session",
            workspace_id=workspace_id,
            session_id=session_id,
            decision="allow",
            details=json.dumps({"before": before, "after": clean_title}),
        )
        return self._sessions.get_by_id(session_id, workspace_id)

    def branch_session(
        self, workspace_id: str, session_id: str, actor_id: str = "user"
    ) -> dict[str, object] | None:
        source = self._sessions.get_by_id(session_id, workspace_id)
        if source is None:
            return None
        branch_id = str(uuid.uuid4())
        source_title = str(source.get("title", "Chat")) or "Chat"
        branch = self._sessions.create(branch_id, workspace_id, f"{source_title[:67]} — branch")
        for message in self._messages.list_by_session(session_id, workspace_id):
            self._messages.create(
                str(uuid.uuid4()),
                workspace_id,
                branch_id,
                str(message.get("role", "assistant")),
                str(message.get("content", "")),
                str(message.get("metadata_json", "{}")),
            )
        self._audit.log(
            actor_id=actor_id,
            action="session_branched",
            resource="session",
            workspace_id=workspace_id,
            session_id=branch_id,
            decision="allow",
            details=json.dumps({"source_session_id": session_id}),
        )
        return branch

    def get_turn_inspector(self, workspace_id: str, trace_id: str) -> dict[str, object] | None:
        trace = self._db.connection.execute(
            "SELECT * FROM traces WHERE id = ? AND workspace_id = ?",
            (trace_id, workspace_id),
        ).fetchone()
        if trace is None:
            return None
        spans = self._rows(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at", (trace_id,)
        )
        model_calls = self._rows(
            "SELECT provider, model, input_token_count, output_token_count, latency_ms, "
            "stop_reason, error FROM model_calls WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        )
        tool_calls = self._rows(
            "SELECT capability_name, decision, status, latency_ms, error "
            "FROM tool_calls WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        )
        audits = self._rows(
            "SELECT action, decision, reason, created_at FROM audit_logs "
            "WHERE trace_id = ? ORDER BY created_at",
            (trace_id,),
        )
        return {
            "trace": self._redact_dict(dict(trace)),
            "spans": [self._redact_dict(row) for row in spans],
            "model_calls": [self._redact_dict(row) for row in model_calls],
            "tool_calls": [self._redact_dict(row) for row in tool_calls],
            "audits": [self._redact_dict(row) for row in audits],
        }

    def _rows(self, sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
        return [dict(row) for row in self._db.connection.execute(sql, params).fetchall()]

    def _redact_dict(self, value: dict[str, Any]) -> dict[str, object]:
        return {key: self._redactor.redact(str(item or "")) for key, item in value.items()}

    @staticmethod
    def _parse_json(value: str) -> dict[str, object]:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
