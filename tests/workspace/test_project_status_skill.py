from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cogito_agent.skill.builtin.project_status import PROJECT_STATUS_MANIFEST, run_project_status
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MemoryRepository, WorkspaceRepository
from cogito_agent.workspace import FileIngestionService, WorkspaceFileRegistry


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    return database


@pytest.fixture
def ws(db: Database) -> str:
    repo = WorkspaceRepository(db)
    w = repo.create("test-ws", "test-workspace")
    return str(w["id"])


class TestProjectStatusSkill:
    def test_manifest_exists(self) -> None:
        assert PROJECT_STATUS_MANIFEST.name == "project_status"
        assert PROJECT_STATUS_MANIFEST.version == "1.0.0"

    def test_run_project_status_creates_artifact(self, db: Database, ws: str) -> None:
        # Setup some test data
        mem_repo = MemoryRepository(db)
        mem_repo.create("mem1", ws, "Working on v0.13 workspace files feature", "task")
        mem_repo.create("mem2", ws, "Need to fix login bug", "task")

        result = run_project_status(db, workspace_id=ws)
        assert result["status"] == "completed"
        assert result["artifact_id"] is not None
        assert result["trace_id"] is not None
        assert result["memory_count"] >= 1

    def test_run_project_status_with_file_chunks(self, db: Database, ws: str) -> None:
        mem_repo = MemoryRepository(db)
        mem_repo.create("mem1", ws, "Project status test memory", "project")

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            registry = WorkspaceFileRegistry(db)
            ing = FileIngestionService(db)
            root = registry.register_root(ws, str(tmp))
            (tmp / "status.md").write_text(
                "# Project Update\n\nWorking on phase 2.", encoding="utf-8"
            )
            ing.scan_root(str(root["id"]), ws)

            result = run_project_status(db, workspace_id=ws)
            assert result["status"] == "completed"
            assert result["file_chunk_count"] >= 1

    def test_run_project_status_creates_inbox(self, db: Database, ws: str) -> None:
        run_project_status(db, workspace_id=ws)
        inbox = db.connection.execute(
            "SELECT * FROM inbox_items WHERE source = 'skill.project_status'"
        ).fetchall()
        assert len(inbox) >= 1

    def test_run_project_status_creates_audit_logs(self, db: Database, ws: str) -> None:
        run_project_status(db, workspace_id=ws)
        logs = db.connection.execute(
            "SELECT * FROM audit_logs WHERE workspace_id = ?", (ws,)
        ).fetchall()
        assert len(logs) >= 1

    def test_run_project_status_trace(self, db: Database, ws: str) -> None:
        result = run_project_status(db, workspace_id=ws)
        trace_id = result["trace_id"]
        assert trace_id is not None
        trace = db.connection.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
        assert trace is not None
