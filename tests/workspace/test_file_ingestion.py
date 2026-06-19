from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository
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
    ws = repo.create("test-ws", "test-workspace")
    return str(ws["id"])


@pytest.fixture
def registry(db: Database) -> WorkspaceFileRegistry:
    return WorkspaceFileRegistry(db)


@pytest.fixture
def ing(db: Database) -> FileIngestionService:
    return FileIngestionService(db)


@pytest.fixture
def tmp_root() -> Path:
    return Path(tempfile.mkdtemp())


class TestTextExtraction:
    def test_extract_md(self, ing: FileIngestionService, tmp_root: Path) -> None:
        f = tmp_root / "test.md"
        f.write_text("# Hello\n\nThis is **markdown**.", encoding="utf-8")
        text = ing._extract_text(f, ".md")
        assert "# Hello" in text
        assert "**markdown**" in text

    def test_extract_json(self, ing: FileIngestionService, tmp_root: Path) -> None:
        f = tmp_root / "test.json"
        f.write_text('{"key": "value", "num": 42}', encoding="utf-8")
        text = ing._extract_text(f, ".json")
        assert '"key"' in text
        assert '"value"' in text

    def test_extract_py(self, ing: FileIngestionService, tmp_root: Path) -> None:
        f = tmp_root / "test.py"
        f.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        text = ing._extract_text(f, ".py")
        assert "def hello()" in text

    def test_extract_ts(self, ing: FileIngestionService, tmp_root: Path) -> None:
        f = tmp_root / "test.ts"
        f.write_text("const x: number = 1;\n", encoding="utf-8")
        text = ing._extract_text(f, ".ts")
        assert "const x" in text

    def test_extract_js(self, ing: FileIngestionService, tmp_root: Path) -> None:
        f = tmp_root / "test.js"
        f.write_text("console.log('hello');\n", encoding="utf-8")
        text = ing._extract_text(f, ".js")
        assert "console.log" in text


class TestScanIdempotency:
    def test_scan_is_idempotent(self, db: Database, ws: str, registry: WorkspaceFileRegistry, ing: FileIngestionService, tmp_root: Path) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        (tmp_root / "test.txt").write_text("hello world", encoding="utf-8")
        r1 = ing.scan_root(rid, ws)
        assert r1["scanned"] == 1
        r2 = ing.scan_root(rid, ws)
        assert r2["scanned"] == 1
        files = registry.list_files(ws)
        assert len(files) == 1


class TestMaxFileSize:
    def test_large_file_ignored(self, db: Database, ws: str, registry: WorkspaceFileRegistry, ing: FileIngestionService, tmp_root: Path) -> None:
        root = registry.register_root(ws, str(tmp_root), max_file_size=10)
        rid = str(root["id"])
        f = tmp_root / "large.txt"
        f.write_text("x" * 100, encoding="utf-8")
        r = ing.scan_root(rid, ws)
        assert r["ignored"] == 1


class TestIgnorePatterns:
    def test_ignore_patterns_respected(self, db: Database, ws: str, registry: WorkspaceFileRegistry, ing: FileIngestionService, tmp_root: Path) -> None:
        root = registry.register_root(ws, str(tmp_root), ignore_patterns="*.log\n.git")
        rid = str(root["id"])
        (tmp_root / "app.log").write_text("log data", encoding="utf-8")
        (tmp_root / "main.py").write_text("print('hi')", encoding="utf-8")
        r = ing.scan_root(rid, ws)
        assert r["ignored"] >= 1
        assert r["scanned"] == 1


class TestChunkCreation:
    def test_chunks_created(self, db: Database, ws: str, registry: WorkspaceFileRegistry, ing: FileIngestionService, tmp_root: Path) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        f = tmp_root / "long.txt"
        f.write_text("\n".join(f"Line {i}" for i in range(100)), encoding="utf-8")
        ing.scan_root(rid, ws)
        files = registry.list_files(ws)
        assert len(files) == 1
        fid = str(files[0]["id"])
        chunks = ing.get_file_chunks(fid)
        assert len(chunks) >= 1
        assert chunks[0]["text"] != ""


class TestParseErrors:
    def test_parse_error_does_not_break_scan(self, db: Database, ws: str, registry: WorkspaceFileRegistry, ing: FileIngestionService, tmp_root: Path) -> None:
        root = registry.register_root(ws, str(tmp_root))
        rid = str(root["id"])
        (tmp_root / "good.txt").write_text("ok", encoding="utf-8")
        bad = tmp_root / "bad.bin"
        bad.write_bytes(b"\x00\x01\x02\xff")
        r = ing.scan_root(rid, ws)
        assert r["scanned"] >= 1
