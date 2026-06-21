from cogito_agent.capability import (
    CapabilityRegistry,
    _validate_json_schema,
)
from cogito_agent.capability.tools import (
    READ_FILE_MANIFEST,
    _read_file,
)
from cogito_agent.shared import CapabilityManifest, CapabilityType, RiskLevel


def make_manifest(input_schema: dict[str, object]) -> CapabilityManifest:
    return CapabilityManifest(
        name="test.tool",
        version="1.0.0",
        type=CapabilityType.tool,
        description="test",
        input_schema=input_schema,
        output_schema={"type": "object"},
        permissions=[],
        risk_level=RiskLevel.low,
        allowed_contexts=["interactive"],
        approval_required=False,
        audit_required=False,
        idempotent=True,
    )


def _dummy_invoke(**kwargs: object) -> object:
    from cogito_agent.capability import ToolResult

    return ToolResult(status="ok", summary="dummy")


def test_register_tool() -> None:
    registry = CapabilityRegistry()
    registry.register("local.file_read", READ_FILE_MANIFEST, _read_file)
    manifest = registry.get_manifest("local.file_read")
    assert manifest is not None
    assert manifest.name == "local.file_read"
    assert manifest.risk_level.value == "medium"


def test_list_tools() -> None:
    registry = CapabilityRegistry()
    registry.register("local.file_read", READ_FILE_MANIFEST, _read_file)
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "local.file_read"


def test_invoke_nonexistent_tool() -> None:
    registry = CapabilityRegistry()
    result = registry.invoke("nonexistent")
    assert result is None


def test_invoke_tool() -> None:
    registry = CapabilityRegistry()
    registry.register("local.file_read", READ_FILE_MANIFEST, _read_file)
    result = registry.invoke("local.file_read", path="/nonexistent")
    assert result is not None
    assert result.status == "error"


def test_invoke_validates_missing_required() -> None:
    registry = CapabilityRegistry()
    manifest = make_manifest(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )
    registry.register("test.tool", manifest, _dummy_invoke)
    result = registry.invoke("test.tool")
    assert result is not None
    assert result.status == "error"
    assert "Missing required field" in (result.error or "")


def test_invoke_validates_type_mismatch() -> None:
    registry = CapabilityRegistry()
    manifest = make_manifest(
        {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
            "required": ["age"],
        }
    )
    registry.register("test.tool", manifest, _dummy_invoke)
    result = registry.invoke("test.tool", age="not_an_int")
    assert result is not None
    assert result.status == "error"
    assert "must be an integer" in (result.error or "")


def test_invoke_validates_enum() -> None:
    registry = CapabilityRegistry()
    manifest = make_manifest(
        {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}},
            "required": ["mode"],
        }
    )
    registry.register("test.tool", manifest, _dummy_invoke)
    result = registry.invoke("test.tool", mode="invalid")
    assert result is not None
    assert result.status == "error"
    assert "must be one of" in (result.error or "")


def test_invoke_passes_valid_input() -> None:
    registry = CapabilityRegistry()
    manifest = make_manifest(
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }
    )
    registry.register("test.tool", manifest, _dummy_invoke)
    result = registry.invoke("test.tool", value="hello")
    assert result is not None
    assert result.status == "ok"


def test_tool_result_has_new_fields() -> None:
    from cogito_agent.capability import ToolResult

    result = ToolResult(
        status="ok",
        summary="test",
        artifacts=[{"path": "/tmp/f", "type": "file"}],
        redactions=["token-abc"],
        lineage=[{"source": "/tmp/f", "tool": "test"}],
    )
    assert result.artifacts == [{"path": "/tmp/f", "type": "file"}]
    assert result.redactions == ["token-abc"]
    assert result.lineage == [{"source": "/tmp/f", "tool": "test"}]


def test_validate_json_schema_required() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    assert _validate_json_schema(schema, {}) is not None
    assert _validate_json_schema(schema, {"x": "ok"}) is None


def test_validate_json_schema_types() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "i": {"type": "integer"},
            "b": {"type": "boolean"},
            "a": {"type": "array", "items": {"type": "string"}},
        },
    }
    assert _validate_json_schema(schema, {"s": "ok", "i": 42, "b": True, "a": ["x"]}) is None
    assert _validate_json_schema(schema, {"s": 1}) is not None
    assert _validate_json_schema(schema, {"i": "bad"}) is not None
    assert _validate_json_schema(schema, {"b": "bad"}) is not None
    assert _validate_json_schema(schema, {"a": [1]}) is not None


def test_registry_unregister() -> None:
    registry = CapabilityRegistry()
    registry.register("test.tool", make_manifest({}), _dummy_invoke)
    assert registry.unregister("test.tool") is True
    assert registry.get_manifest("test.tool") is None
    assert registry.unregister("test.tool") is False
