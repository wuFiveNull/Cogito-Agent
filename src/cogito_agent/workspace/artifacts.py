from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import _row_to_dict, _rows_to_dicts
from cogito_agent.trace import Tracer
from cogito_agent.trace.redaction import RedactionHelper


class ArtifactService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._tracer = Tracer(db)
        self._audit = AuditLogger(db)
        self._redactor = RedactionHelper()

    def create_artifact(
        self,
        workspace_id: str,
        source_type: str,
        title: str,
        artifact_type: str = "markdown",
        mime_type: str = "text/markdown",
        content: str = "",
        source_id: str = "",
        created_by: str = "",
        trace_id: str = "",
    ) -> dict[str, object]:
        aid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        size = len(content.encode("utf-8"))

        content_json = json.dumps({"body": self._redactor.redact(content)})

        self._db.connection.execute(
            "INSERT INTO artifacts"
            " (id, workspace_id, source_type, source_id, title, artifact_type,"
            " mime_type, content_json, content_sha256, size_bytes,"
            " created_by, trace_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, workspace_id, source_type, source_id, title, artifact_type,
             mime_type, content_json, content_sha, size,
             created_by, trace_id, now, now),
        )
        self._db.connection.commit()

        audit_id = self._audit.log(
            actor_id=created_by or "system",
            action="artifact.create",
            resource=f"artifact:{aid}",
            workspace_id=workspace_id,
            trace_id=trace_id,
            reason=f"Created {artifact_type} artifact: {title}",
            redact_details=True,
        )
        self._db.connection.execute(
            "UPDATE artifacts SET audit_id = ? WHERE id = ?",
            (audit_id, aid),
        )
        self._db.connection.commit()

        result = self.get_artifact_by_id(aid)
        assert result is not None
        return result

    def get_artifact_by_id(self, aid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM artifacts WHERE id = ? AND deleted_at IS NULL",
            (aid,),
        )
        return _row_to_dict(cur.fetchone())

    def list_artifacts(
        self,
        workspace_id: str,
        source_type: str = "",
        artifact_type: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        conditions = ["workspace_id = ?", "deleted_at IS NULL"]
        params: list[object] = [workspace_id]
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if artifact_type:
            conditions.append("artifact_type = ?")
            params.append(artifact_type)
        sql = "SELECT * FROM artifacts WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def delete_artifact(self, aid: str) -> bool:
        row = self.get_artifact_by_id(aid)
        if row is None:
            return False
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, aid),
        )
        self._db.connection.commit()

        self._audit.log(
            actor_id="system",
            action="artifact.delete",
            resource=f"artifact:{aid}",
            workspace_id=str(row["workspace_id"]),
            trace_id=str(row.get("trace_id", "")),
            reason=f"Deleted artifact: {row.get('title', '')}",
            redact_details=True,
        )
        return True

    def get_artifact_content(self, aid: str) -> str:
        row = self.get_artifact_by_id(aid)
        if row is None:
            return ""
        content_json = str(row.get("content_json", "{}"))
        try:
            parsed = json.loads(content_json)
            return str(parsed.get("body", ""))
        except (json.JSONDecodeError, TypeError):
            return content_json

    def render_artifact_html(self, aid: str) -> str:
        row = self.get_artifact_by_id(aid)
        if row is None:
            return "<p>Artifact not found.</p>"
        artifact_type = str(row.get("artifact_type", "markdown"))
        raw_content = self.get_artifact_content(aid)
        safe = self._redactor.redact(raw_content)
        if artifact_type == "json":
            import html
            try:
                parsed = json.loads(safe)
                pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                return f"<pre><code>{html.escape(pretty)}</code></pre>"
            except json.JSONDecodeError:
                return f"<pre><code>{html.escape(safe)}</code></pre>"
        if artifact_type == "text":
            import html
            return f"<pre><code>{html.escape(safe)}</code></pre>"
        try:
            import markdown as md_lib
            return str(md_lib.markdown(safe))
        except Exception:
            import html
            return f"<pre><code>{html.escape(safe)}</code></pre>"
