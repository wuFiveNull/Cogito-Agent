import pytest
from pydantic import ValidationError

from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    Permission,
    RiskLevel,
)


def test_valid_manifest() -> None:
    manifest = CapabilityManifest(
        name="local.file_read",
        version="1.0.0",
        type=CapabilityType.tool,
        description="Read a local workspace file.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=[Permission(resource="workspace_file", operations=["read"])],
        risk_level=RiskLevel.medium,
        allowed_contexts=["interactive"],
        approval_required=False,
        audit_required=True,
        idempotent=True,
    )
    assert manifest.name == "local.file_read"
    assert manifest.risk_level == RiskLevel.medium


def test_invalid_manifest_missing() -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest(name="test")  # type: ignore[call-arg]


def test_risk_level_values() -> None:
    assert RiskLevel.low.value == "low"
    assert RiskLevel.critical.value == "critical"
