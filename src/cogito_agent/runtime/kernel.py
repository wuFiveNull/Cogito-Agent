from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.context import ContextEngine, ContextItem
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.memory import CandidateExtractor, MemoryRetriever
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.shared import (
    DecisionType,
    EventType,
    PolicyRequest,
    RuntimeEvent,
    SpanKind,
    TurnState,
    TurnStateMachine,
)
from cogito_agent.storage import Database, MessageRepository, SessionRepository
from cogito_agent.storage.repositories import ApprovalRepository
from cogito_agent.trace import SourceLineage, Tracer

from .budget import TurnBudget


class TurnResult:
    def __init__(
        self,
        state: TurnState,
        output: str = "",
        error: str | None = None,
        tool_summaries: list[dict[str, object]] | None = None,
        sources: list[dict[str, object]] | None = None,
        approval_pending: bool = False,
        approval_id: str | None = None,
    ) -> None:
        self.state = state
        self.output = output
        self.error = error
        self.tool_summaries = tool_summaries or []
        self.sources = sources or []
        self.approval_pending = approval_pending
        self.approval_id = approval_id


class BudgetError(Exception):
    pass


class PolicyDeniedError(Exception):
    pass


class ApprovalRequiredError(Exception):
    def __init__(self, message: str, approval_id: str = "") -> None:
        super().__init__(message)
        self.approval_id = approval_id


class RuntimeKernel:
    def __init__(
        self,
        db: Database,
        budget: TurnBudget | None = None,
        model_adapter: ModelAdapter | None = None,
        capability_registry: CapabilityRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        context_engine: ContextEngine | None = None,
        memory_retriever: MemoryRetriever | None = None,
        candidate_extractor: CandidateExtractor | None = None,
    ) -> None:
        self._db = db
        self._sm = TurnStateMachine()
        self._tracer = Tracer(db)
        self._audit = AuditLogger(db)
        self._lineage = SourceLineage(db)
        self._budget = budget or TurnBudget()
        self._model_adapter = model_adapter
        self._cap_reg = capability_registry
        self._policy = policy_engine or PolicyEngine()
        self._ctx_engine = context_engine or ContextEngine()
        self._mem_retriever = memory_retriever
        self._cand_extractor = candidate_extractor
        self._sess_repo = SessionRepository(db)
        self._msg_repo = MessageRepository(db)
        self._model_call_count = 0
        self._tool_call_count = 0
        self._start_time: datetime | None = None
        self._tool_results: list[dict[str, object]] = []
        self._sources: list[dict[str, object]] = []

    @property
    def state(self) -> TurnState:
        return self._sm.state

    @staticmethod
    def _retry_with_backoff(
        fn: Any,
        max_retries: int = 2,
        base_delay: float = 0.5,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1 + max_retries):
            try:
                return fn()
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
        raise last_error  # type: ignore[misc]

    def process(self, event: RuntimeEvent) -> TurnResult:
        trace = self._tracer.create_trace(
            workspace_id=event.workspace_id,
            root_event_id=event.id,
            session_id=event.session_id,
        )
        span = self._tracer.create_span(trace.id, "process_turn", SpanKind.runtime)
        span.input_summary = f"event={event.type.value}, actor={event.actor_id}"
        self._start_time = datetime.now(UTC)

        try:
            self._sm.transition(TurnState.loading_session)
            self._transition(TurnState.building_context)
            ctx = self._build_context(event)
            self._sources = [
                {"type": c.source_type, "id": c.source_id, "text": c.text}
                for c in ctx if isinstance(c, ContextItem) and c.included
            ]

            self._transition(TurnState.awaiting_model)
            self._check_budget_model()
            self._check_model_policy(event)
            raw_text = (
                event.payload.get("text", "")
                if event.type == EventType.user_message
                else ""
            )
            text = str(raw_text) if raw_text is not None else ""
            model_resp = self._generate_reply(event, text, trace, span)

            self._transition(TurnState.evaluating_result)

            model_result = self._compose_result(event, model_resp, trace, span)
            tool_summaries = list(self._tool_results)

            self._transition(TurnState.composing_result)
            self._transition(TurnState.persisting)
            output_text = model_result.content
            self._persist(event, output_text)
            self._candidate_extract(event, output_text)

            self._audit.log(
                actor_id=event.actor_id,
                action="turn_completed",
                resource="session",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                trace_id=trace.id,
                decision="allow",
                reason="Turn completed",
            )

            self._sm.transition(TurnState.completed)
            result = TurnResult(
                state=TurnState.completed,
                output=output_text,
                tool_summaries=tool_summaries,
                sources=self._sources,
            )

        except BudgetError as exc:
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
            result = TurnResult(
                state=TurnState.failed, error=str(exc), output=str(exc)
            )

        except PolicyDeniedError as exc:
            try:
                self._sm.transition(TurnState.denied)
            except ValueError:
                pass
            result = TurnResult(state=TurnState.denied, error=str(exc))

        except ApprovalRequiredError as exc:
            try:
                self._sm.transition(TurnState.awaiting_approval)
            except ValueError:
                pass
            result = TurnResult(
                state=TurnState.awaiting_approval,
                approval_pending=True,
                approval_id=exc.approval_id,
                error=str(exc),
            )

        except Exception as exc:
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
            error_msg = str(exc)
            result = TurnResult(state=TurnState.failed, error=error_msg)

        self._tracer.end_span(span)
        self._tracer.end_trace(trace)
        span.output_summary = f"state={result.state.value}, error={result.error}"
        return result

    def _transition(self, target: TurnState) -> None:
        self._sm.transition(target)

    def _check_budget_model(self) -> None:
        if not self._budget.can_call_model(self._model_call_count):
            raise BudgetError(
                f"Model call budget exceeded "
                f"({self._model_call_count}/{self._budget.max_model_calls})"
            )
        elapsed = (
            datetime.now(UTC) - (self._start_time or datetime.now(UTC))
        ).total_seconds()
        if elapsed > self._budget.max_wall_time_seconds:
            raise BudgetError(
                f"Wall clock budget exceeded "
                f"({elapsed:.1f}s > {self._budget.max_wall_time_seconds}s)"
            )

    def _check_budget_tool(self) -> None:
        if not self._budget.can_call_tool(self._tool_call_count):
            raise BudgetError(
                f"Tool call budget exceeded "
                f"({self._tool_call_count}/{self._budget.max_tool_calls})"
            )

    def _check_model_policy(self, event: RuntimeEvent) -> None:
        req = PolicyRequest(
            actor_id=event.actor_id,
            capability_name="*",
            operation="call_model",
            resource="model_provider",
            context=event.source.value,
        )
        decision = self._policy.evaluate(req)
        if decision.decision == DecisionType.deny:
            self._audit.log(
                actor_id=event.actor_id, action="call_model",
                resource="model_provider",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                decision="deny", reason=decision.reason,
            )
            raise PolicyDeniedError(f"Model call denied: {decision.reason}")

    def _build_context(self, event: RuntimeEvent) -> list[ContextItem]:
        messages_raw = self._msg_repo.list_by_session(
            event.workspace_id, event.session_id
        )
        recent_messages: list[dict[str, object]] = [
            dict(m) for m in messages_raw[-6:]
        ]
        memories: list[dict[str, object]] = []
        if self._mem_retriever:
            try:
                raw = event.payload.get("text", "")
                query = str(raw) if raw is not None else ""
                memories = self._mem_retriever.search(
                    event.workspace_id, query
                )
            except Exception:
                memories = self._mem_retriever.list_recent(event.workspace_id)
        ctx_items = self._ctx_engine.build(
            recent_messages=recent_messages,
            memories=memories,
            current_message=str(event.payload.get("text", "") or ""),
            db=self._db,
            trace_id="",
            workspace_id=event.workspace_id,
        )
        return ctx_items

    def _generate_reply(
        self, event: RuntimeEvent, message: str,
        trace: object, span: object,
    ) -> ModelResponse:
        if not message.strip():
            return ModelResponse(content="I didn't receive any message.")
        if self._model_adapter is None:
            return ModelResponse(content=f"You said: {message}")
        msgs = self._build_model_messages(event, message, trace)
        call_start = datetime.now(UTC)
        resp: ModelResponse = self._retry_with_backoff(
            lambda: self._model_adapter.chat(msgs),
        )
        latency = int((datetime.now(UTC) - call_start).total_seconds() * 1000)
        self._model_call_count += 1

        self._tracer.log_model_call(
            trace_id=str(getattr(trace, "id", "")),
            span_id=str(getattr(span, "id", "")),
            provider=resp.provider,
            model=resp.model,
            input_token_count=resp.input_tokens,
            output_token_count=resp.output_tokens,
            prompt_summary=message[:200] if message else "",
            response_summary=resp.content[:200] if resp.content else "",
            latency_ms=latency,
            stop_reason=resp.stop_reason,
            error=resp.error,
        )

        if resp.tool_intents and self._cap_reg:
            resp = self._dispatch_tools(event, resp, trace, span)

        return resp

    def _build_model_messages(
        self, event: RuntimeEvent, message: str, trace: object,
    ) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        recent = self._msg_repo.list_by_session(
            event.workspace_id, event.session_id
        )
        for msg in recent[-6:]:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": message})
        return msgs

    def _dispatch_tools(
        self, event: RuntimeEvent, resp: ModelResponse,
        trace: object, span: object,
    ) -> ModelResponse:
        collected_results: list[dict[str, object]] = []
        for intent in resp.tool_intents:
            capability_name = str(intent.get("name", ""))
            if not capability_name:
                continue
            manifest = (
                self._cap_reg.get_manifest(capability_name)
                if self._cap_reg else None
            )
            if manifest is None:
                collected_results.append({
                    "tool": capability_name,
                    "error": "Capability not found",
                })
                self._audit.log(
                    actor_id=event.actor_id, action="call_tool",
                    resource=capability_name,
                    workspace_id=event.workspace_id,
                    session_id=event.session_id,
                    decision="deny",
                    reason="Capability not registered",
                )
                continue

            op = (
                manifest.type.value
                if hasattr(manifest.type, "value")
                else str(manifest.type)
            )
            policy_req = PolicyRequest(
                actor_id=event.actor_id,
                capability_name=capability_name,
                operation=op,
                resource=capability_name,
                context=event.source.value,
            )
            policy_dec = self._policy.evaluate(policy_req)

            if policy_dec.decision == DecisionType.deny:
                collected_results.append({
                    "tool": capability_name,
                    "error": f"Denied: {policy_dec.reason}",
                })
                self._audit.log(
                    actor_id=event.actor_id, action="call_tool",
                    resource=capability_name,
                    workspace_id=event.workspace_id,
                    session_id=event.session_id,
                    trace_id=str(getattr(trace, "id", "")),
                    decision="deny", reason=policy_dec.reason,
                )
                continue

            needs_approval = (
                policy_dec.decision == DecisionType.require_approval
                or manifest.approval_required
            )
            if needs_approval:
                approval_id = self._create_approval(
                    event, capability_name, policy_req, policy_dec
                )
                self._audit.log(
                    actor_id=event.actor_id, action="call_tool",
                    resource=capability_name,
                    workspace_id=event.workspace_id,
                    session_id=event.session_id,
                    trace_id=str(getattr(trace, "id", "")),
                    decision="require_approval",
                    reason=policy_dec.reason,
                )
                raise ApprovalRequiredError(
                    f"Approval required for {capability_name}",
                    approval_id=approval_id,
                )

            self._check_budget_tool()
            raw_args = intent.get("arguments", {})
            if isinstance(raw_args, dict):
                args: dict[str, object] = {str(k): v for k, v in raw_args.items()}
            else:
                args = {}
            tool_start = datetime.now(UTC)

            def _do_invoke() -> object | None:
                return (
                    self._cap_reg.invoke(capability_name, **args)
                    if self._cap_reg else None
                )

            can_retry = manifest.idempotent
            if can_retry:
                tool_result = self._retry_with_backoff(_do_invoke)
            else:
                tool_result = _do_invoke()
            tool_latency = int(
                (datetime.now(UTC) - tool_start).total_seconds() * 1000
            )
            self._tool_call_count += 1

            summary = tool_result.summary if tool_result else ""
            error = tool_result.error if tool_result else None
            status = (
                "ok"
                if tool_result and tool_result.status == "ok"
                else "error"
            )

            collected_results.append({
                "tool": capability_name,
                "summary": summary,
                "error": error,
            })
            self._tool_results.append({
                "tool": capability_name,
                "summary": summary,
                "status": status,
            })

            dec_value = (
                policy_dec.decision.value
                if hasattr(policy_dec.decision, "value")
                else str(policy_dec.decision)
            )
            self._tracer.log_tool_call(
                trace_id=str(getattr(trace, "id", "")),
                span_id=str(getattr(span, "id", "")),
                capability_name=capability_name,
                input_summary=str(args)[:200],
                decision=dec_value,
                status=status,
                output_summary=summary[:200] if summary else "",
                latency_ms=tool_latency,
                error=error,
            )

            self._audit.log(
                actor_id=event.actor_id, action="call_tool",
                resource=capability_name,
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                trace_id=str(getattr(trace, "id", "")),
                decision="allow", reason=policy_dec.reason,
            )

        if collected_results and self._model_adapter:
            follow_up_msgs = self._build_model_messages(event, "", trace)
            follow_up_msgs.append({
                "role": "assistant",
                "content": str(resp.content),
            })
            for r in collected_results:
                follow_up_msgs.append({
                    "role": "tool",
                    "content": str(
                        r.get("summary", "") or r.get("error", "")
                    ),
                })
            follow_up = self._model_adapter.chat(follow_up_msgs)
            self._model_call_count += 1
            return follow_up

        return resp

    def _create_approval(
        self, event: RuntimeEvent, capability_name: str,
        policy_req: PolicyRequest, policy_dec: object,
    ) -> str:
        repo = ApprovalRepository(self._db)
        reason = (
            str(policy_dec.reason)
            if hasattr(policy_dec, "reason")
            else "require_approval"
        )
        record = repo.create(
            workspace_id=event.workspace_id,
            actor_id=event.actor_id,
            capability_name=capability_name,
            operation=str(policy_req.operation),
            resource=str(policy_req.resource),
            reason=reason,
            session_id=event.session_id,
        )
        return str(record.get("id", ""))

    def _compose_result(
        self, event: RuntimeEvent, resp: ModelResponse,
        trace: object, span: object,
    ) -> ModelResponse:
        if resp.error:
            return ModelResponse(content=f"Model error: {resp.error}")
        return resp

    def _candidate_extract(self, event: RuntimeEvent, output: str) -> None:
        if not self._cand_extractor or not output.strip():
            return
        try:
            cur = self._db.connection.execute(
                "SELECT id FROM messages WHERE workspace_id = ?"
                " AND session_id = ? AND role = 'assistant'"
                " ORDER BY rowid DESC LIMIT 1",
                (event.workspace_id, event.session_id),
            )
            row = cur.fetchone()
            source_id = str(row["id"]) if row else event.id
            self._cand_extractor.extract_from_turn(
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                source_message_id=source_id,
                text=output,
            )
        except Exception:
            pass

    def _persist(self, event: RuntimeEvent, output: str) -> None:
        mid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO messages (id, workspace_id, session_id, role, content)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, event.workspace_id, event.session_id, "assistant", output),
        )
        self._db.connection.commit()
