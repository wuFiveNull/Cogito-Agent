from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol


class RunRepositoryPort(Protocol):
    def list_runs(
        self,
        *,
        workspace_id: str | None = None,
        status: str | None = None,
        run_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]: ...
    def get(self, run_id: str) -> dict[str, object] | None: ...
    def list_events(self, run_id: str) -> list[dict[str, object]]: ...
    def list_outputs(self, run_id: str) -> list[dict[str, object]]: ...
    def cancel(self, run_id: str, *, reason: str = "") -> bool: ...
    def retry(self, run_id: str) -> bool: ...


class RunAuditPort(Protocol):
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


class RunApplicationService:
    def __init__(
        self,
        repository: RunRepositoryPort,
        audit: RunAuditPort | None = None,
        retry_dispatcher: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._retry_dispatcher = retry_dispatcher

    def list_runs(
        self,
        *,
        workspace_id: str,
        status: str | None = None,
        run_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        return self._repository.list_runs(
            workspace_id=workspace_id,
            status=status,
            run_type=run_type,
            limit=limit,
        )

    def get_run(self, run_id: str) -> dict[str, object] | None:
        run = self._repository.get(run_id)
        if run is None:
            return None
        result = dict(run)
        result["events"] = self._repository.list_events(run_id)
        result["outputs"] = self._repository.list_outputs(run_id)
        for key in ("input_json", "result_json"):
            try:
                result[key.removesuffix("_json")] = json.loads(str(result.get(key, "{}")))
            except (TypeError, ValueError):
                result[key.removesuffix("_json")] = {}
        return result

    def cancel(
        self,
        run_id: str,
        *,
        workspace_id: str,
        actor_id: str = "console",
        reason: str = "cancelled from console",
    ) -> bool:
        changed = self._repository.cancel(run_id, reason=reason)
        self._audit_mutation(
            actor_id,
            workspace_id,
            run_id,
            "run.cancel",
            "allow" if changed else "deny",
            reason if changed else "run is terminal or missing",
        )
        return changed

    def retry(
        self,
        run_id: str,
        *,
        workspace_id: str,
        actor_id: str = "console",
    ) -> bool:
        run = self._repository.get(run_id)
        changed = self._repository.retry(run_id)
        self._audit_mutation(
            actor_id,
            workspace_id,
            run_id,
            "run.retry",
            "allow" if changed else "deny",
            "retry queued" if changed else "run is not retryable",
        )
        if changed and run is not None and self._retry_dispatcher is not None:
            self._retry_dispatcher(run)
        return changed

    def _audit_mutation(
        self,
        actor_id: str,
        workspace_id: str,
        run_id: str,
        action: str,
        decision: str,
        reason: str,
    ) -> None:
        if self._audit is None:
            return
        self._audit.log(
            actor_id=actor_id,
            action=action,
            resource=f"run:{run_id}",
            workspace_id=workspace_id,
            decision=decision,
            reason=reason,
        )
