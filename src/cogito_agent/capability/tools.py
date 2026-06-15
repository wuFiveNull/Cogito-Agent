from __future__ import annotations

from pathlib import Path

from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    Permission,
    RiskLevel,
)

from .registry import ToolResult


def _read_file(path: str = "") -> ToolResult:
    if not path:
        return ToolResult(
            status="error", summary="Path is required",
            error="Missing path argument",
        )
    try:
        p = Path(path)
        if not p.exists():
            return ToolResult(
                status="error",
                summary=f"File not found: {path}",
                error="File not found",
            )
        content = p.read_text(encoding="utf-8")
        return ToolResult(
            status="ok", summary=f"Read {len(content)} chars",
            data={"content": content, "size": len(content)},
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
    try:
        p = Path(path)
        if not p.is_dir():
            return ToolResult(
                status="error",
                summary=f"Not a directory: {path}",
                error="Not a directory",
            )
        files = sorted(str(f) for f in p.iterdir())
        return ToolResult(
            status="ok", summary=f"Listed {len(files)} entries",
            data={"files": files},
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
