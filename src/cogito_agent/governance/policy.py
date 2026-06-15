from __future__ import annotations

from cogito_agent.shared import DecisionType, PolicyDecision, PolicyRequest


class PolicyRule:
    def __init__(
        self,
        actor: str,
        operation: str,
        context: str,
        decision: DecisionType,
        capability: str = "*",
        resource: str = "*",
    ) -> None:
        self.actor = actor
        self.operation = operation
        self.context = context
        self.decision = decision
        self.capability = capability
        self.resource = resource

    def matches(self, request: PolicyRequest) -> bool:
        return all([
            self.actor == "*" or request.actor_id == self.actor,
            self.operation == "*" or request.operation == self.operation,
            self.context == "*" or request.context == self.context,
            self.capability == "*" or request.capability_name == self.capability,
            self.resource == "*" or request.resource == self.resource,
        ])


class PolicyEngine:
    MVP_MATRIX: list[PolicyRule] = [
        PolicyRule("*", "call_model", "*",
                   DecisionType.allow),
        PolicyRule("*", "tool", "*",
                   DecisionType.allow),
        PolicyRule("user", "read", "interactive",
                   DecisionType.allow_with_audit, resource="workspace_file"),
        PolicyRule("assistant", "write", "interactive",
                   DecisionType.require_approval, resource="workspace_file"),
        PolicyRule("assistant", "delete", "interactive",
                   DecisionType.deny, resource="workspace_file"),
        PolicyRule("user", "read", "interactive",
                   DecisionType.allow, resource="memory"),
        PolicyRule("assistant", "write", "interactive",
                   DecisionType.require_approval, resource="memory"),
        PolicyRule("assistant", "write", "interactive",
                   DecisionType.allow_with_audit, resource="trace_log"),
        PolicyRule("skill", "call", "background",
                   DecisionType.deny, resource="network"),
        PolicyRule("scheduler", "notify", "quiet_hours",
                   DecisionType.deny),
        PolicyRule("scheduler", "execute", "background",
                   DecisionType.allow_with_audit, resource="*"),
        PolicyRule("*", "*", "*", DecisionType.escalate),
    ]

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules = rules or list(self.MVP_MATRIX)

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        for rule in self._rules:
            if rule.matches(request):
                if rule.decision == DecisionType.escalate:
                    return PolicyDecision(
                        decision=DecisionType.deny,
                        reason="No matching policy rule",
                    )
                return PolicyDecision(
                    decision=rule.decision,
                    reason=f"Matched rule: actor={rule.actor}, op={rule.operation}",
                )
        return PolicyDecision(decision=DecisionType.deny, reason="No policy rule matched")
