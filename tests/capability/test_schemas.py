"""Tests: Capability Manifest to tool schema conversion and filtering."""
from __future__ import annotations

import json

from cogito_agent.capability.schemas import filter_available_tools, manifest_to_tool_schema
from cogito_agent.shared import CapabilityManifest, CapabilityType, Permission, RiskLevel


def _make_manifest(
    name: str = "test.tool",
    contexts: list[str] | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version="1.0.0",
        type=CapabilityType.tool,
        description="A test tool",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        output_schema={"type": "object"},
        permissions=[Permission(resource="test", operations=["read"])],
        risk_level=RiskLevel.low,
        allowed_contexts=contexts or ["interactive"],
        approval_required=False,
        audit_required=False,
        idempotent=True,
    )


def test_manifest_to_tool_schema() -> None:
    manifest = _make_manifest("custom.tool")
    schema = manifest_to_tool_schema(manifest)
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "custom.tool"
    assert fn["description"] == "A test tool"
    params = fn["parameters"]
    assert params["type"] == "object"
    assert "query" in params["properties"]
    assert params["required"] == ["query"]


def test_tool_schema_valid_json() -> None:
    manifest = _make_manifest("json.tool")
    schema = manifest_to_tool_schema(manifest)
    serialized = json.dumps(schema)
    parsed = json.loads(serialized)
    assert parsed["function"]["name"] == "json.tool"


def test_filter_interactive_only() -> None:
    manifests = [
        _make_manifest("interactive.tool", contexts=["interactive"]),
        _make_manifest("background.tool", contexts=["background"]),
    ]
    available = filter_available_tools(manifests, interaction_mode="interactive")
    names = [m.name for m in available]
    assert "interactive.tool" in names
    assert "background.tool" not in names


def test_filter_background_allowed() -> None:
    manifests = [
        _make_manifest("interactive.tool", contexts=["interactive"]),
        _make_manifest("both.tool", contexts=["interactive", "background"]),
    ]
    available = filter_available_tools(
        manifests, interaction_mode="background", background_allowed=True,
    )
    names = [m.name for m in available]
    assert "both.tool" in names
    assert "interactive.tool" not in names


def test_filter_disabled_tool_excluded() -> None:
    manifests = [
        _make_manifest("enabled.tool", contexts=["interactive"]),
    ]
    available = filter_available_tools(manifests, interaction_mode="interactive")
    assert len(available) == 1


def test_empty_manifest_list() -> None:
    available = filter_available_tools([], interaction_mode="interactive")
    assert available == []


def test_manifest_input_schema_preserved() -> None:
    manifest = _make_manifest("schema.tool")
    schema = manifest_to_tool_schema(manifest)
    input_schema = manifest.input_schema
    converted_params = schema["function"]["parameters"]
    assert converted_params == input_schema
