from __future__ import annotations

import json
import uuid
from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository
from cogito_agent.storage.session_store import SessionStore
from cogito_agent.shared.redaction import RedactionHelper

from ..markdown import render_safe_markdown


class ChatWorkspaceService:
    """Workspace-scoped application boundary for Console chat operations."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._sessions = SessionRepository(db)
        self._store = SessionStore(db)
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
            messages = self._store.get_history(sid, workspace_id)
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
        all_messages = self._store.get_history(session_id, workspace_id)
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
                    "input_tokens": metadata.get("input_tokens", 0),
                    "output_tokens": metadata.get("output_tokens", 0),
                    "model": metadata.get("model", ""),
                    "latency_ms": metadata.get("latency_ms", 0),
                    "thinking_html": render_safe_markdown(
                        str(metadata.get("thinking", ""))
                    ) if metadata.get("thinking") else "",
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

    def get_turn_inspector(self, workspace_id: str, trace_id: str) -> dict[str, object] | None:
        from cogito_agent.storage.repositories import TraceRepository
        detail = TraceRepository(self._db).get_detail_with_spans(trace_id)
        if detail is None:
            return None
        return {
            "trace": self._redact_dict(detail),
            "spans": [self._redact_dict(row) for row in detail.get("spans", [])],
            "model_calls": [self._redact_dict(row) for row in detail.get("model_calls", [])],
            "tool_calls": [self._redact_dict(row) for row in detail.get("tool_calls", [])],
            "audits": [self._redact_dict(row) for row in detail.get("audits", [])],
        }

    def _redact_dict(self, value: dict[str, Any]) -> dict[str, object]:
        return {key: self._redactor.redact(str(item or "")) for key, item in value.items()}

    @staticmethod
    def _parse_json(value: str) -> dict[str, object]:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
