import tempfile
from pathlib import Path

import pytest

from cogito_agent.capability.tools import _list_files, _read_file, set_sandbox_root


@pytest.fixture(autouse=True)
def _sandbox() -> None:
    import cogito_agent.capability.tools as cap_tools
    old_root = cap_tools._SANDBOX_ROOT  # type: ignore[attr-defined]
    set_sandbox_root(tempfile.gettempdir())
    yield
    set_sandbox_root(old_root)


def test_read_file_not_found() -> None:
    import tempfile
    d = tempfile.gettempdir()
    result = _read_file(path=d + "/nonexistent_file_xyz.txt")
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


def test_read_file_outside_sandbox() -> None:
    result = _read_file(path="C:\\Windows\\win.ini")
    assert result.status == "error"
    assert "Access denied" in result.summary


def test_list_files_success() -> None:
    with tempfile.TemporaryDirectory() as d:
        set_sandbox_root(d)
        Path(d, "a.txt").write_text("a")
        Path(d, "b.txt").write_text("b")
        result = _list_files(path=d)
        assert result.status == "ok"
        files = result.data.get("files", [])
        assert isinstance(files, list)
        assert len(files) >= 2


def test_list_files_not_directory() -> None:
    import tempfile
    d = tempfile.gettempdir()
    result = _list_files(path=d + "/nonexistent_dir_xyz")
    assert result.status == "error"


def test_list_files_outside_sandbox() -> None:
    result = _list_files(path="C:\\Windows")
    assert result.status == "error"
    assert "Access denied" in result.summary


def test_read_file_has_artifacts_and_lineage() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("data")
        f.flush()
        result = _read_file(path=f.name)
        assert result.status == "ok"
        assert len(result.artifacts) >= 1
        assert result.artifacts[0]["type"] == "file"
        assert len(result.lineage) >= 1
        assert result.lineage[0]["tool"] == "local.file_read"
