from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository
from cogito_agent.workspace import WorkspaceFileRegistry


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
def tmp_root() -> Path:
    return Path(tempfile.mkdtemp())


class TestWorkspaceRootRegistration:
    def test_register_root(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root), "Test Root")
        assert root["workspace_id"] == ws
        assert root["label"] == "Test Root"
        assert root["status"] == "active"

    def test_list_roots(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        registry.register_root(ws, str(tmp_root), "Root 1")
        r2 = Path(tempfile.mkdtemp())
        registry.register_root(ws, str(r2), "Root 2")
        roots = registry.list_roots(ws)
        assert len(roots) == 2

    def test_delete_root(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root), "Temp Root")
        rid = str(root["id"])
        assert registry.delete_root(rid) is True
        assert registry.get_root_by_id(rid) is None


class TestPathTraversal:
    def test_path_traversal_deny(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        safe = registry.resolve_safe_path(rid, "../etc/passwd")
        assert safe is None

    def test_absolute_path_deny(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        safe = registry.resolve_safe_path(rid, "/etc/passwd")
        assert safe is None

    def test_normal_path_resolves(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        (tmp_root / "test.txt").write_text("hello", encoding="utf-8")
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        safe = registry.resolve_safe_path(rid, "test.txt")
        assert safe is not None
        assert safe.name == "test.txt"


class TestFileRegistration:
    def test_register_file(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        (tmp_root / "hello.md").write_text("# Hello", encoding="utf-8")
        f = registry.register_file(ws, rid, "hello.md", "hello.md", "text/markdown")
        assert f["file_name"] == "hello.md"
        assert f["status"] == "active"

    def test_get_file_by_path(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        (tmp_root / "test.py").write_text("x = 1", encoding="utf-8")
        registry.register_file(ws, rid, "test.py", "test.py")
        f = registry.get_file_by_path(ws, "test.py")
        assert f is not None
        assert f["file_name"] == "test.py"

    def test_remove_file(
        self, db: Database, ws: str, registry: WorkspaceFileRegistry, tmp_root: Path
    ) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        (tmp_root / "del.txt").write_text("delete me", encoding="utf-8")
        f = registry.register_file(ws, rid, "del.txt", "del.txt")
        fid = str(f["id"])
        assert registry.remove_file(fid) is True
        assert registry.get_file_by_id(fid) is None


class TestIgnorePatterns:
    def test_ignore_by_extension(self) -> None:
        assert WorkspaceFileRegistry.matches_ignore_patterns("test.log", "*.log")
        assert not WorkspaceFileRegistry.matches_ignore_patterns("test.txt", "*.log")

    def test_ignore_by_name(self) -> None:
        assert WorkspaceFileRegistry.matches_ignore_patterns("__pycache__/foo.py", "__pycache__")
        assert WorkspaceFileRegistry.matches_ignore_patterns(".DS_Store", ".DS_Store")

    def test_ignore_multi_pattern(self) -> None:
        patterns = "*.log\n.DS_Store\n.git\n__pycache__"
        assert WorkspaceFileRegistry.matches_ignore_patterns("app.log", patterns)
        assert WorkspaceFileRegistry.matches_ignore_patterns(".git/config", patterns)
        assert not WorkspaceFileRegistry.matches_ignore_patterns("src/main.py", patterns)


class TestWorkspaceIsolation:
    def test_isolation_between_workspaces(
        self, db: Database, registry: WorkspaceFileRegistry
    ) -> None:
        ws_repo = WorkspaceRepository(db)
        ws1 = str(ws_repo.create("ws1", "ws1")["id"])
        ws2 = str(ws_repo.create("ws2", "ws2")["id"])
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            r1 = registry.register_root(ws1, d1)
            r2 = registry.register_root(ws2, d2)
            (Path(d1) / "file1.txt").write_text("content1", encoding="utf-8")
            (Path(d2) / "file2.txt").write_text("content2", encoding="utf-8")
            registry.register_file(ws1, str(r1["id"]), "file1.txt", "file1.txt")
            registry.register_file(ws2, str(r2["id"]), "file2.txt", "file2.txt")
            files_ws1 = registry.list_files(ws1)
            files_ws2 = registry.list_files(ws2)
            assert len(files_ws1) == 1
            assert len(files_ws2) == 1
            assert files_ws1[0]["file_name"] == "file1.txt"
            assert files_ws2[0]["file_name"] == "file2.txt"

    def test_id_mutations_require_matching_workspace(
        self,
        db: Database,
        registry: WorkspaceFileRegistry,
        tmp_root: Path,
    ) -> None:
        ws_repo = WorkspaceRepository(db)
        ws1 = str(ws_repo.create("ws-scope-1", "ws-scope-1")["id"])
        ws2 = str(ws_repo.create("ws-scope-2", "ws-scope-2")["id"])
        root = registry.register_root(ws1, str(tmp_root))
        record = registry.register_file(
            ws1,
            str(root["id"]),
            "private.txt",
            "private.txt",
        )
        file_id = str(record["id"])
        assert registry.get_file_by_id(file_id, ws2) is None
        assert registry.remove_file(file_id, ws2) is False
        assert registry.get_file_by_id(file_id, ws1) is not None
