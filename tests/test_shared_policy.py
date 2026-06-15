import pytest
from pydantic import ValidationError

from cogito_agent.shared import DecisionType, PolicyDecision, PolicyRequest


def test_policy_request() -> None:
    req = PolicyRequest(
        actor_id="assistant",
        capability_name="local.file_write",
        resource="workspace_file",
        operation="write",
        context="interactive",
    )
    assert req.actor_id == "assistant"


def test_invalid_policy_request() -> None:
    with pytest.raises(ValidationError):
        PolicyRequest(actor_id="test")  # type: ignore[call-arg]


def test_decision_types() -> None:
    assert DecisionType.allow.value == "allow"
    assert DecisionType.deny.value == "deny"
    assert DecisionType.require_approval.value == "require_approval"


def test_policy_decision() -> None:
    d = PolicyDecision(decision=DecisionType.deny, reason="Not allowed in MVP")
    assert d.decision == DecisionType.deny
    assert d.reason == "Not allowed in MVP"
