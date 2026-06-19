from __future__ import annotations

from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    Permission,
    RiskLevel,
)

SCAN_FILE_MANIFEST = CapabilityManifest(
    name="workspace.file.scan",
    version="1.0.0",
    type=CapabilityType.tool,
    description="Scan a workspace root and index its files.",
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "root_id": {"type": "string"},
        },
        "required": ["workspace_id", "root_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "scanned": {"type": "integer"},
            "errors": {"type": "integer"},
            "ignored": {"type": "integer"},
        },
    },
    permissions=[Permission(resource="workspace_file", operations=["read", "scan"])],
    risk_level=RiskLevel.medium,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

SEARCH_FILE_MANIFEST = CapabilityManifest(
    name="workspace.file.search",
    version="1.0.0",
    type=CapabilityType.tool,
    description="Search indexed file chunks by query text.",
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["workspace_id", "query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "results": {"type": "array"},
        },
    },
    permissions=[Permission(resource="workspace_file", operations=["read"])],
    risk_level=RiskLevel.low,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

READ_FILE_MANIFEST_V2 = CapabilityManifest(
    name="workspace.file.read",
    version="1.0.0",
    type=CapabilityType.tool,
    description="Read content of an indexed workspace file.",
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "file_id": {"type": "string"},
        },
        "required": ["workspace_id", "file_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "file_name": {"type": "string"},
            "mime_type": {"type": "string"},
        },
    },
    permissions=[Permission(resource="workspace_file", operations=["read"])],
    risk_level=RiskLevel.medium,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=True,
)

WRITE_ARTIFACT_MANIFEST = CapabilityManifest(
    name="workspace.file.write_artifact",
    version="1.0.0",
    type=CapabilityType.tool,
    description="Create an artifact in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "title": {"type": "string"},
            "artifact_type": {"type": "string", "enum": ["markdown", "json", "text", "report"]},
            "content": {"type": "string"},
            "source_type": {"type": "string"},
        },
        "required": ["workspace_id", "title", "content"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string"},
            "title": {"type": "string"},
        },
    },
    permissions=[Permission(resource="artifact", operations=["write"])],
    risk_level=RiskLevel.medium,
    allowed_contexts=["interactive", "background"],
    approval_required=False,
    audit_required=True,
    idempotent=False,
)

REMOVE_FILE_MANIFEST = CapabilityManifest(
    name="workspace.file.remove_from_index",
    version="1.0.0",
    type=CapabilityType.tool,
    description="Remove a file from the workspace index.",
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "file_id": {"type": "string"},
        },
        "required": ["workspace_id", "file_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "removed": {"type": "boolean"},
        },
    },
    permissions=[Permission(resource="workspace_file", operations=["delete"])],
    risk_level=RiskLevel.medium,
    allowed_contexts=["interactive"],
    approval_required=True,
    audit_required=True,
    idempotent=True,
)

_ALL_FILE_MANIFESTS = [
    SCAN_FILE_MANIFEST,
    SEARCH_FILE_MANIFEST,
    READ_FILE_MANIFEST_V2,
    WRITE_ARTIFACT_MANIFEST,
    REMOVE_FILE_MANIFEST,
]
