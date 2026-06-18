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


FILE_POLICY_RULES: list[PolicyRule] = [
    PolicyRule("assistant", "read", "interactive",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("assistant", "scan", "interactive",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("assistant", "search", "interactive",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("assistant", "write", "interactive",
               DecisionType.require_approval, resource="artifact"),
    PolicyRule("assistant", "delete", "interactive",
               DecisionType.require_approval, resource="workspace_file"),
    PolicyRule("scheduler", "read", "background",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("scheduler", "scan", "background",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("scheduler", "search", "background",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("scheduler", "write", "background",
               DecisionType.deny, resource="artifact"),
    PolicyRule("scheduler", "write", "background",
               DecisionType.require_approval, resource="artifact"),
    PolicyRule("skill", "read", "interactive",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("skill", "scan", "interactive",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("skill", "search", "interactive",
               DecisionType.allow_with_audit, resource="workspace_file"),
    PolicyRule("skill", "write", "interactive",
               DecisionType.allow_with_audit, resource="artifact"),
    PolicyRule("skill", "write", "background",
               DecisionType.require_approval, resource="artifact"),
]


class PolicyEngine:
    MVP_MATRIX: list[PolicyRule] = [
        # ── Interactive: explicit rules evaluated first ──────────────
        PolicyRule("assistant", "delete", "interactive",
                   DecisionType.deny, resource="workspace_file"),
        PolicyRule("assistant", "write", "interactive",
                   DecisionType.require_approval, resource="workspace_file"),
        PolicyRule("assistant", "write", "interactive",
                   DecisionType.require_approval, resource="memory"),
        PolicyRule("assistant", "write", "interactive",
                   DecisionType.allow_with_audit, resource="trace_log"),
        PolicyRule("user", "read", "interactive",
                   DecisionType.allow_with_audit, resource="workspace_file"),
        PolicyRule("user", "read", "interactive",
                   DecisionType.allow, resource="memory"),
        # ── Background: strict deny before allow ────────────────────
        PolicyRule("*", "delete", "background",
                   DecisionType.deny, resource="*"),
        PolicyRule("*", "write", "background",
                   DecisionType.deny, resource="workspace_file"),
        PolicyRule("*", "write", "background",
                   DecisionType.deny, resource="memory"),
        PolicyRule("*", "execute", "background",
                   DecisionType.deny, resource="shell"),
        PolicyRule("*", "read", "background",
                   DecisionType.deny, resource="secret"),
        PolicyRule("skill", "call", "background",
                   DecisionType.deny, resource="network"),
        PolicyRule("scheduler", "notify", "quiet_hours",
                   DecisionType.deny),
        PolicyRule("scheduler", "execute", "background",
                   DecisionType.allow_with_audit, resource="*"),
        PolicyRule("*", "notify", "background",
                   DecisionType.allow_with_audit),
        PolicyRule("*", "read", "background",
                   DecisionType.allow_with_audit, resource="workspace_file"),
        PolicyRule("maintenance", "execute", "background",
                   DecisionType.allow_with_audit, resource="database"),
        PolicyRule("*", "call_model", "background",
                   DecisionType.allow_with_audit),
        PolicyRule("*", "call_tool", "background",
                   DecisionType.allow_with_audit, resource="*"),
        # ── Catch-all for interactive (non-wildcard) ─────────────────
        PolicyRule("*", "call_model", "*",
                   DecisionType.allow),
        PolicyRule("*", "tool", "*",
                   DecisionType.allow),
        PolicyRule("*", "send", "*",
                   DecisionType.allow_with_audit, capability="notification.send"),
        # ── Final fallback ──────────────────────────────────────────
        PolicyRule("*", "*", "*", DecisionType.escalate),
    ]

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules = rules or list(self.MVP_MATRIX) + FILE_POLICY_RULES

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
