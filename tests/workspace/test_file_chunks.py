from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository
from cogito_agent.workspace import FileIngestionService, FileRetriever, WorkspaceFileRegistry


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    return database


@pytest.fixture
def ws(db: Database) -> str:
    repo = WorkspaceRepository(db)
    ws = repo.create("test-ws", "test-workspace")
    return str(ws["id"])


@pytest.fixture
def registry(db: Database) -> WorkspaceFileRegistry:
    return WorkspaceFileRegistry(db)


@pytest.fixture
def ing(db: Database) -> FileIngestionService:
    return FileIngestionService(db)


@pytest.fixture
def retriever(db: Database) -> FileRetriever:
    return FileRetriever(db)


@pytest.fixture
def tmp_root() -> Path:
    return Path(tempfile.mkdtemp())


def _setup_files(db: Database, ws: str, tmp_root: Path) -> tuple[WorkspaceFileRegistry, FileIngestionService, str]:
    registry = WorkspaceFileRegistry(db)
    ing = FileIngestionService(db)
    root = registry.register_root(ws, str(tmp_root))
    rid = str(root["id"])
    (tmp_root / "hello.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello, {name}!'",
        encoding="utf-8",
    )
    (tmp_root / "data.json").write_text(
        '{"users": [{"name": "Alice", "age": 30}]}',
        encoding="utf-8",
    )
    ing.scan_root(rid, ws)
    return registry, ing, rid


class TestFTSFileSearch:
    def test_search_returns_results(self, db: Database, ws: str, retriever: FileRetriever, tmp_root: Path) -> None:
        _setup_files(db, ws, tmp_root)
        results = retriever.search(ws, "greet", use_embedding=False)
        assert len(results) >= 1
        r = results[0]
        assert "greet" in str(r.get("text", ""))
        assert "source_lineage" in r
        lineage = r["source_lineage"]
        assert isinstance(lineage, dict)
        assert "file_name" in lineage

    def test_search_no_results(self, db: Database, ws: str, retriever: FileRetriever, tmp_root: Path) -> None:
        _setup_files(db, ws, tmp_root)
        results = retriever.search(ws, "xyznonexistent12345", use_embedding=False)
        assert len(results) == 0

    def test_search_includes_path_and_lines(self, db: Database, ws: str, retriever: FileRetriever, tmp_root: Path) -> None:
        _setup_files(db, ws, tmp_root)
        results = retriever.search(ws, "greet", use_embedding=False)
        if results:
            r = results[0]
            lineage = r["source_lineage"]
            assert isinstance(lineage, dict)
            assert "path" in lineage
            assert "lines" in lineage
            assert "chunk_id" in lineage


class TestEmbeddingFallback:
    def test_embedding_fallback_to_fts(self, db: Database, ws: str, retriever: FileRetriever, tmp_root: Path) -> None:
        _setup_files(db, ws, tmp_root)
        results = retriever.search(ws, "greet", use_embedding=True)
        assert len(results) >= 1
