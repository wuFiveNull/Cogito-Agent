import tempfile
from pathlib import Path

from cogito_agent.capability.tools import _list_files, _read_file


def test_read_file_not_found() -> None:
    result = _read_file(path="/nonexistent/file.txt")
    assert result.status == "error"
    assert "not found" in result.summary.lower()


def test_read_file_empty_path() -> None:
    result = _read_file()
    assert result.status == "error"


def test_read_file_success() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        f.flush()
        result = _read_file(path=f.name)
        assert result.status == "ok"
        content = result.data.get("content", "")
        assert content == "hello world"


def test_list_files_success() -> None:
    with tempfile.TemporaryDirectory() as d:
        Path(d, "a.txt").write_text("a")
        Path(d, "b.txt").write_text("b")
        result = _list_files(path=d)
        assert result.status == "ok"
        files = result.data.get("files", [])
        assert isinstance(files, list)
        assert len(files) >= 2


def test_list_files_not_directory() -> None:
    result = _list_files(path="/nonexistent")
    assert result.status == "error"
