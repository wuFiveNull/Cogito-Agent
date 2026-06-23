from __future__ import annotations

from abc import ABC, abstractmethod

from cogito_agent.models import ModelAdapter
from cogito_agent.shared import DecisionType, PolicyDecision, PolicyRequest

_POLICY_LLM_JUDGE_PROMPT = (
    "You are a policy evaluation agent. A request does not match any explicit "
    "policy rule. Determine whether it should be allowed, denied, or require approval.\n\n"
    "Rules of thumb:\n"
    "- Background delete/write to workspace/memory → deny\n"
    "- Interactive read/scan → allow_with_audit\n"
    "- Interactive write/delete to workspace → require_approval\n"
    "- Model/tool calls in any context → allow\n"
    "- Network egress in background → deny\n"
    "- If uncertain → deny (fail closed)\n\n"
    "Respond with JSON only: {\"decision\": \"allow|deny|require_approval\", \"reason\": \"...\"}"
)


class PolicyRule:
    """A single declarative policy rule.

    All fields default to ``"*"`` (wildcard). A rule matches a request when
    every non-wildcard field equals the corresponding request field.
    """

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
        return all(
            [
                self.actor == "*" or request.actor_id == self.actor,
                self.operation == "*" or request.operation == self.operation,
                self.context == "*" or request.context == self.context,
                self.capability == "*" or request.capability_name == self.capability,
                self.resource == "*" or request.resource == self.resource,
            ]
        )


# ── Context mapping ──────────────────────────────────────────────────────────
# Policy requests use two context "schemas":
#   1. High-level categories: "interactive" / "background" (used by executor,
#      scheduler, gate, dispatcher, CLI, skill runner).
#   2. Raw event-source values: "cli" / "api" / "scheduler" / "webhook" / "skill"
#      (used by kernel.py ``_check_model_policy``).
#
# These sets map raw event sources to the category they belong to.
_INTERACTIVE_SOURCES: frozenset[str] = frozenset({"interactive", "cli", "api"})
_BACKGROUND_SOURCES: frozenset[str] = frozenset({"background", "quiet_hours", "scheduler", "webhook", "skill"})


# ── Strategy hierarchy ───────────────────────────────────────────────────────
# Each strategy owns a set of rules for a single domain.  Strategies are
# tried in order; the first that returns a non-None decision wins.  This
# replaces the old single monolithic MVP_MATRIX + FILE_POLICY_RULES list
# whose wildcard ordering caused priority bugs and dead-code accumulation.


class PolicyStrategy(ABC):
    """Base class for a domain-specific policy strategy."""

    @abstractmethod
    def evaluate(self, request: PolicyRequest) -> PolicyDecision | None:
        """Evaluate *request* against this strategy's rules.

        Return a :class:`PolicyDecision` when the domain applies, or
        ``None`` to let the next strategy try.
        """


class InteractiveStrategy(PolicyStrategy):
    """Rules for interactive (user-facing) operations."""

    _RULES: list[PolicyRule] = [
        # ── Assistant interactive ──────────────────────────────────────
        PolicyRule(
            "assistant", "delete", "interactive", DecisionType.deny,
            resource="workspace_file",
        ),
        PolicyRule(
            "assistant", "write", "interactive", DecisionType.require_approval,
            resource="workspace_file",
        ),
        PolicyRule(
            "assistant", "write", "interactive", DecisionType.require_approval,
            resource="memory",
        ),
        PolicyRule(
            "assistant", "write", "interactive", DecisionType.allow_with_audit,
            resource="trace_log",
        ),
        PolicyRule(
            "assistant", "read", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "assistant", "scan", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "assistant", "search", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "assistant", "write", "interactive", DecisionType.require_approval,
            resource="artifact",
        ),
        PolicyRule(
            "assistant", "delete", "interactive", DecisionType.require_approval,
            resource="workspace_file",
        ),
        # ── User interactive ───────────────────────────────────────────
        PolicyRule(
            "user", "read", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "user", "read", "interactive", DecisionType.allow,
            resource="memory",
        ),
        # ── Skill interactive ──────────────────────────────────────────
        PolicyRule(
            "skill", "read", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "skill", "scan", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "skill", "search", "interactive", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "skill", "write", "interactive", DecisionType.allow_with_audit,
            resource="artifact",
        ),
        # ── Interactive catch-all (context-independent) ─────────────────
        PolicyRule("*", "call_model", "*", DecisionType.allow),
        PolicyRule("*", "tool", "*", DecisionType.allow),
        PolicyRule(
            "*", "send", "*", DecisionType.allow_with_audit,
            capability="notification.send",
        ),
    ]

    def evaluate(self, request: PolicyRequest) -> PolicyDecision | None:
        if request.context not in _INTERACTIVE_SOURCES:
            return None
        for rule in self._RULES:
            if rule.matches(request):
                return PolicyDecision(
                    decision=rule.decision,
                    reason=f"Matched rule: actor={rule.actor}, op={rule.operation}",
                )
        return None


class BackgroundStrategy(PolicyStrategy):
    """Rules for background / scheduled operations."""

    _RULES: list[PolicyRule] = [
        # ── Hard denies first (safety) ─────────────────────────────────
        PolicyRule("*", "delete", "background", DecisionType.deny, resource="*"),
        PolicyRule("*", "write", "background", DecisionType.deny, resource="workspace_file"),
        PolicyRule("*", "write", "background", DecisionType.deny, resource="memory"),
        PolicyRule("*", "execute", "background", DecisionType.deny, resource="shell"),
        PolicyRule("*", "read", "background", DecisionType.deny, resource="secret"),
        PolicyRule("skill", "call", "background", DecisionType.deny, resource="network"),
        PolicyRule("scheduler", "notify", "quiet_hours", DecisionType.deny),
        PolicyRule(
            "scheduler", "write", "background", DecisionType.deny,
            resource="artifact",
        ),
        # ── Conditionally allowed ──────────────────────────────────────
        PolicyRule(
            "scheduler", "execute", "background", DecisionType.allow_with_audit,
            resource="*",
        ),
        PolicyRule(
            "scheduler", "write", "background", DecisionType.require_approval,
            resource="artifact",
        ),
        PolicyRule(
            "scheduler", "read", "background", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "scheduler", "scan", "background", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "scheduler", "search", "background", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule(
            "skill", "write", "background", DecisionType.require_approval,
            resource="artifact",
        ),
        PolicyRule(
            "maintenance", "execute", "background", DecisionType.allow_with_audit,
            resource="database",
        ),
        # ── Broad allow background ─────────────────────────────────────
        PolicyRule("*", "notify", "background", DecisionType.allow_with_audit),
        PolicyRule(
            "*", "read", "background", DecisionType.allow_with_audit,
            resource="workspace_file",
        ),
        PolicyRule("*", "call_model", "background", DecisionType.allow_with_audit),
        PolicyRule(
            "*", "call_tool", "background", DecisionType.allow_with_audit,
            resource="*",
        ),
    ]

    def evaluate(self, request: PolicyRequest) -> PolicyDecision | None:
        if request.context not in _BACKGROUND_SOURCES:
            return None
        for rule in self._RULES:
            if rule.matches(request):
                return PolicyDecision(
                    decision=rule.decision,
                    reason=f"Matched rule: actor={rule.actor}, op={rule.operation}",
                )
        return None


class FallbackStrategy(PolicyStrategy):
    """Catch-all strategy: LLM-based judgment or deny (fail-closed).

    Always applies — it is the last strategy in every engine.
    """

    def __init__(self, llm_adapter: ModelAdapter | None = None) -> None:
        self._llm = llm_adapter

    def set_llm_adapter(self, adapter: ModelAdapter | None) -> None:
        self._llm = adapter

    def evaluate(self, request: PolicyRequest) -> PolicyDecision | None:
        return self._llm_fallback(request)

    def _llm_fallback(self, request: PolicyRequest) -> PolicyDecision:
        """Ask the LLM to decide when no rule matches.

        If no LLM is available, deny (fail-closed for security).
        """
        if not self._llm:
            return PolicyDecision(
                decision=DecisionType.deny,
                reason="No matching policy rule and no LLM fallback",
            )
        try:
            import json

            messages = [
                {"role": "system", "content": _POLICY_LLM_JUDGE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Actor: {request.actor_id}\n"
                        f"Capability: {request.capability_name}\n"
                        f"Operation: {request.operation}\n"
                        f"Resource: {request.resource}\n"
                        f"Context: {request.context}\n\n"
                        "What should the decision be?"
                    ),
                },
            ]
            resp = self._llm.chat(messages)
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0]
            parsed = json.loads(raw)
            decision_str = str(parsed.get("decision", "deny")).strip().lower()
            reason = str(parsed.get("reason", "LLM judged"))[:200]
            decision_map = {
                "allow": DecisionType.allow_with_audit,
                "deny": DecisionType.deny,
                "require_approval": DecisionType.require_approval,
            }
            return PolicyDecision(
                decision=decision_map.get(decision_str, DecisionType.deny),
                reason=f"LLM fallback: {reason}",
            )
        except Exception:
            return PolicyDecision(
                decision=DecisionType.deny,
                reason="LLM fallback failed, denied by default",
            )


class CustomRulesStrategy(PolicyStrategy):
    """Wraps an externally-supplied list of :class:`PolicyRule` objects.

    Used when callers pass ``rules=`` to :class:`PolicyEngine`.  An
    ``escalate`` rule is treated as "not applicable" so that the
    :class:`FallbackStrategy` can take over.
    """

    def __init__(self, rules: list[PolicyRule]) -> None:
        self._rules = rules

    def evaluate(self, request: PolicyRequest) -> PolicyDecision | None:
        for rule in self._rules:
            if rule.matches(request):
                if rule.decision == DecisionType.escalate:
                    return None  # hand over to FallbackStrategy
                return PolicyDecision(
                    decision=rule.decision,
                    reason=f"Matched rule: actor={rule.actor}, op={rule.operation}",
                )
        return None


# ── Facade ──────────────────────────────────────────────────────────────────


class PolicyEngine:
    """Policy evaluation facade.

    Maintains an ordered list of domain-specific strategies.  Each
    ``evaluate()`` call delegates to the first applicable strategy.

    When no ``rules`` are given the engine uses three built-in strategies:

    1. :class:`InteractiveStrategy` — interactive-context rules
    2. :class:`BackgroundStrategy`  — background / quiet-hours rules
    3. :class:`FallbackStrategy`    — LLM judge or deny
    """

    def __init__(
        self,
        rules: list[PolicyRule] | None = None,
        llm_adapter: ModelAdapter | None = None,
    ) -> None:
        self._llm = llm_adapter
        if rules is not None:
            self._strategies: list[PolicyStrategy] = [
                CustomRulesStrategy(rules),
                FallbackStrategy(llm_adapter),
            ]
        else:
            self._interactive = InteractiveStrategy()
            self._background = BackgroundStrategy()
            self._fallback = FallbackStrategy(llm_adapter)
            self._strategies = [
                self._interactive,
                self._background,
                self._fallback,
            ]

    def set_llm_adapter(self, llm_adapter: ModelAdapter | None) -> None:
        """Inject a light LLM adapter for unhandled-rule fallback."""
        self._llm = llm_adapter
        self._fallback.set_llm_adapter(llm_adapter)

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        for strategy in self._strategies:
            decision = strategy.evaluate(request)
            if decision is not None:
                return decision
        return PolicyDecision(
            decision=DecisionType.deny,
            reason="No policy strategy matched the request",
        )
