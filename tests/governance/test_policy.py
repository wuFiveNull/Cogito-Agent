from cogito_agent.governance import PolicyEngine
from cogito_agent.shared import DecisionType, PolicyRequest


def test_allow_user_read() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="user",
        capability_name="local.file_read",
        resource="workspace_file",
        operation="read",
        context="interactive",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.allow_with_audit


def test_deny_assistant_delete() -> None:
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


def test_require_approval_assistant_write() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="assistant",
        capability_name="local.file_write",
        resource="workspace_file",
        operation="write",
        context="interactive",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.require_approval


def test_deny_skill_background_network() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="skill",
        capability_name="network.http_get",
        resource="network",
        operation="call",
        context="background",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny


def test_unknown_matches_catchall() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="unknown",
        capability_name="unknown.tool",
        resource="unknown",
        operation="unknown",
        context="unknown",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny


def test_background_deny_delete() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="local.file_delete",
        resource="*",
        operation="delete",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_deny_file_write() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="skill",
        capability_name="local.file_write",
        resource="workspace_file",
        operation="write",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_deny_secret_read() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="secret.get",
        resource="secret",
        operation="read",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_deny_shell_execute() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="local.shell",
        resource="shell",
        operation="execute",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_allow_file_read() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="local.file_read",
        resource="workspace_file",
        operation="read",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.allow_with_audit


def test_background_allow_model_call() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="model.invoke",
        resource="model",
        operation="call_model",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.allow_with_audit


def test_custom_rules() -> None:
    from cogito_agent.governance.policy import PolicyRule

    engine = PolicyEngine(rules=[
        PolicyRule("*", "read", "*", DecisionType.allow),
        PolicyRule("*", "*", "*", DecisionType.escalate),
    ])
    req = PolicyRequest(
        actor_id="test",
        capability_name="any",
        resource="any",
        operation="read",
        context="any",
    )
    assert engine.evaluate(req).decision == DecisionType.allow
