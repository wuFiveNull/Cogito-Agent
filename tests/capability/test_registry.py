from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.tools import READ_FILE_MANIFEST, _read_file


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
