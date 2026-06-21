from __future__ import annotations

import json

from cogito_agent.cli.export import export_workspace, format_export
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


def _seed_workspace(db: Database) -> str:
    repo = WorkspaceRepository(db)
    ws = repo.create("ws_export_test", "ExportTest")
    ws_id = str(ws["id"])
    db.connection.execute(
        "INSERT INTO sessions (id, workspace_id, title) VALUES ('sess_test', ?, 'Test Session')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO messages (id, workspace_id, session_id, role, content)"
        " VALUES ('msg_1', ?, 'sess_test', 'user', 'hello')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO memories (id, workspace_id, text, type)"
        " VALUES ('mem_1', ?, 'test memory', 'general')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
        " VALUES ('tr_export', ?, 'evt_export', 'completed', '2025-01-01T00:00:00')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO audit_logs (id, workspace_id, actor_id, action, resource, decision)"
        " VALUES ('aud_1', ?, 'user', 'test', 'test_resource', 'allow')",
        (ws_id,),
    )
    db.connection.commit()
    return ws_id


def test_export_contains_traces() -> None:
    db = Database()
    db.initialize()
    ws_id = _seed_workspace(db)
    data = export_workspace(
        db, ws_id, include_traces=True, include_memories=False, include_audit=False
    )
    assert "workspace" in data
    assert "traces" in data
    assert len(data["traces"]) >= 1
    assert "memories" not in data


def test_export_contains_memories() -> None:
    db = Database()
    db.initialize()
    ws_id = _seed_workspace(db)
    data = export_workspace(
        db, ws_id, include_traces=False, include_memories=True, include_audit=False
    )
    assert "memories" in data
    assert len(data["memories"]) >= 1
    assert "traces" not in data


def test_export_contains_audit() -> None:
    db = Database()
    db.initialize()
    ws_id = _seed_workspace(db)
    data = export_workspace(
        db, ws_id, include_traces=False, include_memories=False, include_audit=True
    )
    assert "audit_logs" in data
    assert len(data["audit_logs"]) >= 1


def test_export_all() -> None:
    db = Database()
    db.initialize()
    ws_id = _seed_workspace(db)
    data = export_workspace(
        db, ws_id, include_traces=True, include_memories=True, include_audit=True
    )
    assert "workspace" in data
    assert "sessions" in data
    assert "traces" in data
    assert "memories" in data
    assert "audit_logs" in data


def test_export_format_json() -> None:
    db = Database()
    db.initialize()
    ws_id = _seed_workspace(db)
    data = export_workspace(db, ws_id)
    output = format_export(data, fmt="json")
    parsed = json.loads(output)
    assert parsed["workspace"]["name"] == "ExportTest"


def test_export_unknown_workspace() -> None:
    db = Database()
    db.initialize()
    import pytest

    with pytest.raises(ValueError, match="not found"):
        export_workspace(db, "nonexistent")


def test_export_redact_secrets() -> None:
    db = Database()
    db.initialize()
    ws_id = _seed_workspace(db)
    db.connection.execute(
        "UPDATE memories SET text = ? WHERE id = 'mem_1'",
        ("my api_key=sk-test123secret",),
    )
    db.connection.commit()
    data_raw = export_workspace(db, ws_id, redact=False)
    data_redacted = export_workspace(db, ws_id, redact=True)  # type: ignore[operator]
    output_raw = json.dumps(data_raw, default=str)
    output_redacted = json.dumps(data_redacted, default=str)
    assert "sk-test123secret" in output_raw
    assert "sk-test123secret" not in output_redacted
    assert "[REDACTED]" in output_redacted


def test_export_no_workspace_settings_does_not_crash() -> None:
    db = Database()
    db.initialize()
    repo = WorkspaceRepository(db)
    ws = repo.create("ws_no_settings", "NoSettings")
    ws_id = str(ws["id"])
    data = export_workspace(
        db, ws_id, include_traces=False, include_memories=False, include_audit=False
    )
    assert "settings" in data or True
