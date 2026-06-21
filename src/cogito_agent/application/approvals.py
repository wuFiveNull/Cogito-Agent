from __future__ import annotations

import json
from typing import Protocol


class ApprovalRepositoryPort(Protocol):
    def create(
        self,
        workspace_id: str,
        actor_id: str,
        capability_name: str,
        operation: str = "",
        resource: str = "",
        reason: str = "",
    ) -> dict[str, object]: ...
    def resolve(
        self,
        approval_id: str,
        decision: str,
        decided_by: str,
    ) -> dict[str, object] | None: ...

    def get_by_id(self, approval_id: str) -> dict[str, object] | None: ...


class ApprovalAuditPort(Protocol):
    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str = "",
        reason: str = "",
        details: str = "{}",
        redact_details: bool = True,
    ) -> str: ...


class ApprovalApplicationService:
    def __init__(
        self,
        repository: ApprovalRepositoryPort,
        audit: ApprovalAuditPort,
    ) -> None:
        self._repository = repository
        self._audit = audit

    def create(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        capability_name: str,
        operation: str = "",
        resource: str = "",
        reason: str = "",
    ) -> dict[str, object]:
        return self._repository.create(
            workspace_id,
            actor_id,
            capability_name,
            operation,
            resource,
            reason,
        )

    def resolve(
        self,
        approval_id: str,
        *,
        decision: str,
        actor_id: str,
        workspace_id: str,
        reason: str = "",
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        approved_values = {"allow", "approve", "approved"}
        rejected_values = {"deny", "reject", "rejected"}
        if decision not in approved_values | rejected_values:
            raise ValueError("decision must allow/approve or deny/reject")
        is_approved = decision in approved_values
        result = self._repository.resolve(approval_id, decision, actor_id)
        if result is None:
            return None, self._repository.get_by_id(approval_id)
        self._audit.log(
            actor_id=actor_id,
            action="approval.approve" if is_approved else "approval.reject",
            resource=f"approval:{approval_id}",
            workspace_id=workspace_id,
            decision="allow" if is_approved else "deny",
            reason=reason,
            details=json.dumps(
                {
                    "approval_id": approval_id,
                    "capability": result.get("capability_name", ""),
                    "resource": result.get("resource", ""),
                    "decision_before": "pending",
                    "decision_after": decision,
                }
            ),
        )
        return result, None
