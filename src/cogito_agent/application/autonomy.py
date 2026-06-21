from __future__ import annotations

from cogito_agent.autonomy import DecisionStore, FeedbackStore, FeedbackValue


class AutonomyApplicationService:
    def __init__(
        self,
        decisions: DecisionStore,
        feedback: FeedbackStore,
    ) -> None:
        self._decisions = decisions
        self._feedback = feedback

    def record_feedback(
        self,
        decision_id: str,
        *,
        value: str,
        comment: str = "",
    ) -> str | None:
        decision = self._decisions.get_decision(decision_id)
        if decision is None:
            return None
        FeedbackValue(value)
        return self._feedback.record_feedback(
            decision_id=decision_id,
            event_id=str(decision.get("event_id", "")),
            value=value,
            comment=comment,
            workspace_id=str(decision.get("workspace_id", "*") or "*"),
            trace_id=str(decision.get("trace_id", "")),
        )
