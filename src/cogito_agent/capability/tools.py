from __future__ import annotations

import os
from pathlib import Path

from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    Permission,
    RiskLevel,
)

from .registry import ToolResult

_SANDBOX_ROOT: Path | None = None


def set_sandbox_root(path: str | Path | None) -> None:
    global _SANDBOX_ROOT
    if path is None:
        env_root = os.environ.get("COGITO_WORKSPACE_ROOT")
        if env_root:
            _SANDBOX_ROOT = Path(env_root).resolve()
        else:
            _SANDBOX_ROOT = Path.cwd() / "workspace"
    else:
        _SANDBOX_ROOT = Path(path).resolve()


def get_sandbox_root() -> Path:
    if _SANDBOX_ROOT is None:
        set_sandbox_root(None)
    assert _SANDBOX_ROOT is not None
    return _SANDBOX_ROOT


def _resolve_safe_path(requested: str) -> Path | None:
    if not requested:
        return None
    try:
        resolved = Path(requested).resolve()
        root = get_sandbox_root()
        root_str = str(root).rstrip("\\/")
        resolved_str = str(resolved).rstrip("\\/")
        # On Windows, compare case-insensitively
        if os.name == "nt":
            if not resolved_str.lower().startswith(root_str.lower()):
                return None
        else:
            if not resolved_str.startswith(root_str):
                return None
        return resolved
    except (OSError, ValueError):
        return None


def _read_file(path: str = "") -> ToolResult:
    if not path:
        return ToolResult(
            status="error", summary="Path is required",
            error="Missing path argument",
        )
    safe = _resolve_safe_path(path)
    if safe is None:
        return ToolResult(
            status="error",
            summary="Access denied",
            error=f"Path outside sandbox root: {path}",
        )
    try:
        if not safe.exists():
            return ToolResult(
                status="error",
                summary=f"File not found: {path}",
                error="File not found",
            )
        content = safe.read_text(encoding="utf-8")
        return ToolResult(
            status="ok", summary=f"Read {len(content)} chars",
            data={"content": content, "size": len(content)},
            artifacts=[{"path": str(safe), "type": "file"}],
            lineage=[{"source": str(safe), "tool": "local.file_read"}],
        )
    except Exception as e:
        return ToolResult(
            status="error", summary="Failed to read file", error=str(e),
        )


def _list_files(path: str = "") -> ToolResult:
    if not path:
        return ToolResult(
            status="error", summary="Path is required",
            error="Missing path argument",
        )
    safe = _resolve_safe_path(path)
    if safe is None:
        return ToolResult(
            status="error",
            summary="Access denied",
            error=f"Path outside sandbox root: {path}",
        )
    try:
        if not safe.is_dir():
            return ToolResult(
                status="error",
                summary=f"Not a directory: {path}",
                error="Not a directory",
            )
        files = sorted(str(f) for f in safe.iterdir())
        return ToolResult(
            status="ok", summary=f"Listed {len(files)} entries",
            data={"files": files},
            artifacts=[{"path": str(safe), "type": "directory"}],
            lineage=[{"source": str(safe), "tool": "local.file_list"}],
        )
    except Exception as e:
        return ToolResult(
            status="error", summary="Failed to list directory",
            error=str(e),
        )


READ_FILE_MANIFEST = CapabilityManifest(
    name="local.file_read",
    version="1.0.0",
    type=CapabilityType.tool,
    description="Read contents of a local workspace file.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    output_schema={
        "type": "object",
        "properties": {"content": {"type": "string"}},
    },
    permissions=[Permission(resource="workspace_file", operations=["read"])],
    risk_level=RiskLevel.medium,
    allowed_contexts=["interactive"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

LIST_FILES_MANIFEST = CapabilityManifest(
    name="local.file_list",
    version="1.0.0",
    type=CapabilityType.tool,
    description="List files in a local directory.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "files": {"type": "array", "items": {"type": "string"}},
        },
    },
    permissions=[Permission(resource="workspace_file", operations=["read"])],
    risk_level=RiskLevel.medium,
    allowed_contexts=["interactive"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)
