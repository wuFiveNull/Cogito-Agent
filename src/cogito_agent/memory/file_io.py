"""Atomic file operations for memory .md files.

Ensures crash-safe writes via temp-file + rename pattern,
and hash-based dedup to avoid unnecessary disk writes.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_FILE_DIR = "system"


def memory_file_path(workspace_path: str, filename: str) -> Path:
    """Return the path to a memory .md file under workspace_path/system/."""
    return Path(workspace_path) / _MEMORY_FILE_DIR / filename


def ensure_memory_dir(workspace_path: str) -> Path:
    """Create the system/ subdirectory under workspace_path if missing."""
    path = Path(workspace_path) / _MEMORY_FILE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_memory_file(workspace_path: str, filename: str) -> str:
    """Read a memory .md file, returning empty string if missing."""
    fpath = memory_file_path(workspace_path, filename)
    try:
        return fpath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.warning("Failed to read %s: %s", filename, e)
        return ""


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_file_hash(workspace_path: str, filename: str) -> str | None:
    """Return SHA-256 of current file content, or None if file doesn't exist."""
    content = read_memory_file(workspace_path, filename)
    if not content:
        return None
    return _content_hash(content)


def atomic_write_memory_file(
    workspace_path: str,
    filename: str,
    content: str,
) -> bool:
    """Write content to a memory .md file atomically.

    Uses temp-file + rename pattern for crash safety. Skips the write if
    the content hash matches the existing file (no change).

    Returns True if the file was written, False if skipped (no change).
    """
    new_hash = _content_hash(content)
    current_hash = _current_file_hash(workspace_path, filename)
    if current_hash == new_hash:
        return False  # unchanged, skip write

    fpath = memory_file_path(workspace_path, filename)
    ensure_memory_dir(workspace_path)

    # Atomic write: write to temp file, then rename
    tmp: tempfile.NamedTemporaryFile | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(fpath.parent),
            prefix=f".{filename}.tmp.",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        os.replace(tmp_path, str(fpath))
        return True
    except Exception as e:
        logger.warning("Failed to write %s: %s", filename, e)
        # Clean up temp file if rename failed
        if tmp is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return False
