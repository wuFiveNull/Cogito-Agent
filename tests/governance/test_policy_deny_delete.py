from cogito_agent.governance import PolicyEngine
from cogito_agent.shared import DecisionType, PolicyRequest


def test_deny_assistant_delete_workspace_file() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="assistant",
        capability_name="local.file_delete",
        resource="workspace_file",
        operation="delete",
        context="interactive",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny


def test_deny_unknown_actor() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="scheduler",
        capability_name="any",
        resource="any",
        operation="write",
        context="background",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny
