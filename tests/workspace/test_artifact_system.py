from __future__ import annotations

import pytest

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository
from cogito_agent.workspace import ArtifactService


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


@pytest.fixture
def svc(db: Database) -> ArtifactService:
    return ArtifactService(db)


class TestArtifactCreate:
    def test_create_markdown_artifact(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(
            workspace_id=ws,
            source_type="skill",
            title="Test Report",
            artifact_type="markdown",
            content="# Hello\nThis is a test.",
            created_by="test",
        )
        assert art["title"] == "Test Report"
        assert art["artifact_type"] == "markdown"
        assert art["source_type"] == "skill"

    def test_create_json_artifact(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(
            workspace_id=ws,
            source_type="manual",
            title="Config Dump",
            artifact_type="json",
            content='{"key": "value"}',
        )
        assert art["artifact_type"] == "json"

    def test_create_text_artifact(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(
            workspace_id=ws,
            source_type="system",
            title="Log Output",
            artifact_type="text",
            content="line1\nline2\nline3",
        )
        assert art["artifact_type"] == "text"


class TestArtifactList:
    def test_list_artifacts(self, db: Database, ws: str, svc: ArtifactService) -> None:
        svc.create_artifact(ws, "skill", "A1", content="c1")
        svc.create_artifact(ws, "manual", "A2", content="c2")
        svc.create_artifact(ws, "system", "A3", content="c3")
        all_arts = svc.list_artifacts(ws)
        assert len(all_arts) == 3

    def test_list_by_source_type(self, db: Database, ws: str, svc: ArtifactService) -> None:
        svc.create_artifact(ws, "skill", "S1", content="c")
        svc.create_artifact(ws, "manual", "M1", content="c")
        skills = svc.list_artifacts(ws, source_type="skill")
        assert len(skills) == 1
        assert skills[0]["title"] == "S1"


class TestArtifactDetail:
    def test_get_artifact_by_id(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(ws, "test", "Detail Test", content="# Detail")
        fetched = svc.get_artifact_by_id(str(art["id"]))
        assert fetched is not None
        assert fetched["title"] == "Detail Test"

    def test_get_content(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(ws, "test", "Content", content="Hello World")
        content = svc.get_artifact_content(str(art["id"]))
        assert "Hello World" in content

    def test_workspace_scoped_lookup_rejects_other_workspace(
        self,
        db: Database,
        ws: str,
        svc: ArtifactService,
    ) -> None:
        art = svc.create_artifact(ws, "test", "Private", content="private")
        assert svc.get_artifact_by_id(str(art["id"]), "other-workspace") is None


class TestArtifactDelete:
    def test_delete_artifact(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(ws, "test", "Delete Me", content="bye")
        aid = str(art["id"])
        assert svc.delete_artifact(aid) is True
        assert svc.get_artifact_by_id(aid) is None

    def test_delete_nonexistent(self, db: Database, ws: str, svc: ArtifactService) -> None:
        assert svc.delete_artifact("nonexistent") is False

    def test_workspace_scoped_delete_rejects_other_workspace(
        self,
        db: Database,
        ws: str,
        svc: ArtifactService,
    ) -> None:
        art = svc.create_artifact(ws, "test", "Keep Me", content="safe")
        aid = str(art["id"])
        assert svc.delete_artifact(aid, "other-workspace") is False
        assert svc.get_artifact_by_id(aid, ws) is not None


class TestArtifactRender:
    def test_render_markdown(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(ws, "test", "Render", artifact_type="markdown", content="# H1")
        html = svc.render_artifact_html(str(art["id"]))
        assert "<h1>" in html or "H1" in html

    def test_render_json(self, db: Database, ws: str, svc: ArtifactService) -> None:
        art = svc.create_artifact(
            ws, "test", "JSON Render", artifact_type="json", content='{"a":1}'
        )
        html = svc.render_artifact_html(str(art["id"]))
        assert "a" in html
