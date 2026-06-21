from __future__ import annotations

import base64
import mimetypes
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


_IMAGE_MIME_PREFIXES = {"image/", "application/octet-stream"}


def _is_image_mime(mime: str) -> bool:
    return mime.startswith("image/")


def _read_file(path: str = "") -> ToolResult:
    if not path:
        return ToolResult(
            status="error",
            summary="Path is required",
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
        mime_type, _ = mimetypes.guess_type(str(safe))
        if mime_type and _is_image_mime(mime_type):
            raw = safe.read_bytes()
            b64_data = base64.b64encode(raw).decode("ascii")
            data_uri = f"data:{mime_type};base64,{b64_data}"
            return ToolResult(
                status="ok",
                summary=f"Read image ({len(raw)} bytes, {mime_type})",
                data={
                    "content": f"[Image: {safe.name}]",
                    "size": len(raw),
                    "mime_type": mime_type,
                    "image_b64": data_uri,
                },
                artifacts=[{"path": str(safe), "type": "image"}],
                lineage=[{"source": str(safe), "tool": "local.file_read"}],
            )
        content = safe.read_text(encoding="utf-8")
        return ToolResult(
            status="ok",
            summary=f"Read {len(content)} chars",
            data={"content": content, "size": len(content)},
            artifacts=[{"path": str(safe), "type": "file"}],
            lineage=[{"source": str(safe), "tool": "local.file_read"}],
        )
    except Exception as e:
        return ToolResult(
            status="error",
            summary="Failed to read file",
            error=str(e),
        )


def _list_files(path: str = "") -> ToolResult:
    if not path:
        return ToolResult(
            status="error",
            summary="Path is required",
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
            status="ok",
            summary=f"Listed {len(files)} entries",
            data={"files": files},
            artifacts=[{"path": str(safe), "type": "directory"}],
            lineage=[{"source": str(safe), "tool": "local.file_list"}],
        )
    except Exception as e:
        return ToolResult(
            status="error",
            summary="Failed to list directory",
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


REGISTER_MEME_MANIFEST = CapabilityManifest(
    name="register_meme",
    version="1.0.0",
    type=CapabilityType.tool,
    description=(
        "Register an already-uploaded image as a reusable meme/sticker. "
        "Does NOT call a vision model. Provide name and description manually."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "string",
                "description": "ID of the uploaded image attachment (att_xxx)",
            },
            "name": {"type": "string", "description": "Short name, e.g. 'Confused Dog'"},
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Alias search terms",
            },
            "description": {
                "type": "string",
                "description": "What the image shows and its expression meaning",
            },
            "emotions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Emotions expressed",
            },
            "use_cases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "When to send this meme",
            },
            "avoid_cases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "When NOT to send",
            },
            "text_on_image": {"type": "string", "description": "Visible text in the image"},
        },
        "required": ["attachment_id", "name", "description"],
    },
    output_schema={
        "type": "object",
        "properties": {"result": {"type": "string"}},
    },
    permissions=[Permission(resource="attachment", operations=["read"])],
    risk_level=RiskLevel.low,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

ANALYZE_MEME_MANIFEST = CapabilityManifest(
    name="analyze_meme",
    version="1.0.0",
    type=CapabilityType.tool,
    description=(
        "Use the vision model to analyze an image and auto-generate a meme profile. "
        "Only call this when the user explicitly wants VLM analysis for a new meme. "
        "Do NOT call this when sending a meme."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "string",
                "description": "ID of the uploaded image attachment (att_xxx)",
            },
            "force_refresh": {
                "type": "boolean",
                "description": "Force re-analysis even if profile exists",
                "default": False,
            },
        },
        "required": ["attachment_id"],
    },
    output_schema={
        "type": "object",
        "properties": {"result": {"type": "string"}},
    },
    permissions=[Permission(resource="attachment", operations=["read"])],
    risk_level=RiskLevel.low,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

SEARCH_MEMES_MANIFEST = CapabilityManifest(
    name="search_memes",
    version="1.0.0",
    type=CapabilityType.tool,
    description=(
        "Search registered memes by emotion, topic, or description. "
        "Returns name, description, emotions, and use cases. "
        "Does NOT read image bytes or call the vision model."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keyword, e.g. 'happy', 'confused', 'congratulations'",
            },
            "limit": {
                "type": "integer",
                "description": "Max results",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {"result": {"type": "string"}},
    },
    permissions=[Permission(resource="meme", operations=["read"])],
    risk_level=RiskLevel.low,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

SEND_MEME_MANIFEST = CapabilityManifest(
    name="send_meme",
    version="1.0.0",
    type=CapabilityType.tool,
    description=(
        "Send a registered meme by its ID. "
        "Does NOT call the vision model. "
        "Use search_memes first to find the right meme_id."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "meme_id": {"type": "string", "description": "ID of the registered meme (meme_xxx)"},
            "caption": {"type": "string", "description": "Optional text caption", "default": ""},
        },
        "required": ["meme_id"],
    },
    output_schema={
        "type": "object",
        "properties": {"result": {"type": "string"}},
    },
    permissions=[
        Permission(resource="meme", operations=["read"]),
        Permission(resource="attachment", operations=["read"]),
    ],
    risk_level=RiskLevel.low,
    allowed_contexts=["interactive"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

INSPECT_IMAGE_MANIFEST = CapabilityManifest(
    name="inspect_image",
    version="1.0.0",
    type=CapabilityType.tool,
    description=(
        "Read visual information from an already-uploaded image attachment. "
        "Use this only when existing observations are insufficient "
        "for the current task. Provide a narrow, task-specific prompt."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "string",
                "description": "ID of the uploaded image attachment (att_xxx)",
            },
            "prompt": {
                "type": "string",
                "description": "Specific visual question to ask about the image",
            },
            "force_refresh": {
                "type": "boolean",
                "description": "Force a new vision model call even if a cached observation exists",
                "default": False,
            },
        },
        "required": ["attachment_id", "prompt"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {"type": "string"},
        },
    },
    permissions=[Permission(resource="attachment", operations=["read"])],
    risk_level=RiskLevel.low,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=False,
)
