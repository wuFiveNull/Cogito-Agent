from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cogito_agent.queue.message import InboundMessage

from cogito_agent.context import (
    ContextEngine,
    ContextItem,
    PromptBuilder,
)
from cogito_agent.execution import (
    CapabilityExecutionRequest,
)
from cogito_agent.memory import ConsolidationService
from cogito_agent.models import (
    ModelAdapter,
    ModelResponse,
    ModelRouteEvent,
    ModelRouteEventType,
    StreamGenerator,
)
from cogito_agent.models.messages import (
    ContentPart,
    ImagePart,
    has_image,
    normalize_content,
)
from cogito_agent.retrieval import MemoryRecallResult, MemoryRetrievalService
from cogito_agent.retrieval.query import MemoryQueryBuilder
from cogito_agent.shared import (
    DecisionType,
    EventSource,
    EventType,
    PolicyRequest,
    RuntimeEvent,
    SpanKind,
    TurnState,
    TurnStateMachine,
)
from cogito_agent.shared.safety import wrap_untrusted
from cogito_agent.shared.stream_events import StreamEvent, StreamEventType

from .budget import TurnBudget
from .ports import (
    RuntimeArtifactWriterPort,
    RuntimeCapabilityExecutorPort,
    RuntimeServices,
    VisionObservationPort,
)

_CONSOLIDATION_GUARD_THRESHOLD = 30  # max unconsolidated messages before guard
_TOOL_CHAIN_TERMINATED = (
    "Tool chain terminated: maximum tool rounds reached. "
    "Results from completed tools have been applied."
)
from .result_composer import ComposedResult, ResultComposer


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
        trace_id: str | None = None,
        composed_result: ComposedResult | None = None,
    ) -> None:
        self.state = state
        self.output = output
        self.error = error
        self.tool_summaries = tool_summaries or []
        self.sources = sources or []
        self.approval_pending = approval_pending
        self.approval_id = approval_id
        self.trace_id = trace_id
        self.composed_result = composed_result


logger = logging.getLogger(__name__)


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
        services: RuntimeServices,
        budget: TurnBudget | None = None,
        model_adapter: ModelAdapter | None = None,
        context_engine: ContextEngine | None = None,
        memory_retrieval_service: MemoryRetrievalService | None = None,
        capability_executor: RuntimeCapabilityExecutorPort | None = None,
        artifact_writer: RuntimeArtifactWriterPort | None = None,
        max_tool_rounds: int = 3,
        presence: Any = None,
        workspace_path: str = "",
    ) -> None:
        self._sm = TurnStateMachine()
        self._budget = budget or TurnBudget()
        self._model_adapter = model_adapter
        resolved = services
        self._services = resolved
        self._cap_reg = resolved.capability_catalog
        self._policy = resolved.policy
        self._persistence = resolved.persistence
        self._tracer = resolved.tracer
        self._audit = resolved.audit
        self._cap_executor: RuntimeCapabilityExecutorPort | None = (
            capability_executor or resolved.capability_executor
        )
        self._ctx_engine = context_engine or ContextEngine()
        self._memory_retrieval_service = memory_retrieval_service
        self._workspace_path = workspace_path
        self._query_builder_for_retrieval = MemoryQueryBuilder()
        self._model_call_count = 0
        self._tool_call_count = 0
        self._start_time: datetime | None = None
        self._presence = presence
        self._tool_results: list[dict[str, object]] = []
        self._sources: list[dict[str, object]] = []
        self._max_tool_rounds = max_tool_rounds
        self._prompt_builder = PromptBuilder()
        self._result_composer = ResultComposer()
        self._extra_content: list[ContentPart] = []
        self._current_memories: list[dict[str, object]] = []
        self._current_recall_result: MemoryRecallResult | None = None
        self._current_retrieval_trace_id: str = ""
        self._current_ctx: list[ContextItem] | None = None
        self._vision_service: VisionObservationPort | None = None
        self._meme_service: Any = None
        self._memory_service: Any = None
        self._consolidation_service: ConsolidationService | None = None
        self._vision_pipeline: Any = None
        if self._cap_executor is None and self._cap_reg is not None:
            raise ValueError("capability_registry requires a governed capability executor")

    def set_vision_service(self, service: VisionObservationPort) -> None:
        self._vision_service = service
        from .vision_pipeline import VisionPipeline

        self._vision_pipeline = VisionPipeline(
            model_adapter=self._model_adapter,
            vision_service=service,
            tracer=self._tracer,
            bind_route_observer=self._bind_route_observer,
        )

    def set_meme_service(self, service: Any) -> None:
        self._meme_service = service

    def set_memory_service(self, service: Any) -> None:
        self._memory_service = service

    def set_consolidation_service(self, service: ConsolidationService | None) -> None:
        self._consolidation_service = service

    def _run_vision_pipeline(
        self,
        extra_content: list[ContentPart],
        user_text: str,
        trace: object,
        span: object,
        event: RuntimeEvent | None = None,
    ) -> tuple[list[ContentPart], str]:
        """If images present, run vision pipeline via VisionPipeline helper."""
        from .vision_pipeline import VisionPipeline

        pipeline = self._vision_pipeline or VisionPipeline(
            model_adapter=self._model_adapter,
            vision_service=self._vision_service,
            tracer=self._tracer,
            bind_route_observer=self._bind_route_observer,
        )
        result_content, result_text = pipeline.run_pipeline(
            extra_content, user_text, trace, span, event=event,
        )

        # Count the model call if the pipeline used the primary adapter
        if has_image(extra_content) and not (
            self._vision_service is not None and self._vision_service.has_vision_capability
        ):
            self._model_call_count += 1

        return result_content, result_text

    def _build_vision_messages(
        self,
        image_parts: list[ImagePart],
        instruction: str,
    ) -> list[dict[str, object]]:
        """Delegate to VisionPipeline."""
        if self._vision_pipeline is not None:
            return self._vision_pipeline.build_vision_messages(image_parts, instruction)
        from .vision_pipeline import VisionPipeline

        return VisionPipeline.build_vision_messages(image_parts, instruction)

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
                    delay = base_delay * (2**attempt)
                    time.sleep(delay)
        raise last_error  # type: ignore[misc]

    def _get_tool_schemas(self, actor: str = "assistant") -> list[dict[str, object]]:
        provider = self._services.tool_schema_provider
        if provider is not None:
            return provider.get_tool_schemas(actor=actor)
        return []

    def process(self, event: RuntimeEvent) -> TurnResult:
        trace, span = self._prepare_turn_setup(event, "process_turn")

        try:
            ctx, text = self._run_pre_model_phase(event, trace)

            model_resp = self._generate_reply(event, text, trace, span, ctx=ctx)

            # Multi-round tool loop
            self._transition(TurnState.planning_tool)
            tool_round = 0
            while model_resp.tool_intents and self._cap_reg and tool_round < self._max_tool_rounds:
                tool_round += 1
                model_resp = self._dispatch_tools(event, model_resp, trace, span)

            if tool_round >= self._max_tool_rounds and model_resp.tool_intents:
                model_resp = ModelResponse(content=_TOOL_CHAIN_TERMINATED)

            model_result, output_text = self._run_after_turn(event, model_resp, trace, span)
            tool_summaries = list(self._tool_results)

            result = TurnResult(
                state=TurnState.completed,
                output=output_text,
                tool_summaries=tool_summaries,
                sources=self._sources,
                trace_id=trace.id,
                composed_result=model_result,
            )

        except BudgetError as exc:
            self._safe_transition(self._sm, TurnState.failed)
            result = TurnResult(
                state=TurnState.failed,
                error=str(exc),
                output=str(exc),
                trace_id=trace.id,
            )

        except PolicyDeniedError as exc:
            self._safe_transition(self._sm, TurnState.denied)
            result = TurnResult(
                state=TurnState.denied,
                error=str(exc),
                trace_id=trace.id,
            )

        except ApprovalRequiredError as exc:
            self._safe_transition(self._sm, TurnState.waiting_approval)
            result = TurnResult(
                state=TurnState.waiting_approval,
                approval_pending=True,
                approval_id=exc.approval_id,
                error=str(exc),
                trace_id=trace.id,
            )

        except Exception as exc:
            self._safe_transition(self._sm, TurnState.failed)
            result = TurnResult(
                state=TurnState.failed,
                error=str(exc),
                trace_id=trace.id,
            )

        self._cleanup_turn(trace, span, state_value=result.state.value, error=result.error)
        return result

    def _stream_generate_reply(
        self,
        event: RuntimeEvent,
        message: str,
        trace: object,
        span: object,
        ctx: list[ContextItem] | None = None,
        tool_schemas: list[dict[str, object]] | None = None,
        streaming_enabled: bool = True,
        max_retries: int = 2,
    ) -> Generator[StreamEvent, None, ModelResponse]:
        extra_content = self._get_extra_content(event)
        has_multimodal = bool(extra_content) or bool(event.payload.get("content"))
        has_text = bool(message.strip())
        if not has_text and not has_multimodal:
            yield StreamEvent(
                type=StreamEventType.delta,
                data={"delta": "I didn't receive any message."},
            )
            return ModelResponse(content="I didn't receive any message.")

        msgs = self._build_model_messages(event, message, trace, ctx=ctx)
        self._bind_route_observer(event, trace, span)
        call_start = datetime.now(UTC)

        preferred_role = str(event.payload.get("_preferred_role", "") or "")

        echo = f"You said: {message}" if self._model_adapter is None else ""
        gen = StreamGenerator(
            self._model_adapter,
            msgs,
            echo_text=echo,
            streaming_enabled=streaming_enabled,
            tool_schemas=tool_schemas,
            route_role=preferred_role,
        )

        attempt = 0
        first_delta_yielded = False
        while attempt <= max_retries:
            try:
                for chunk in gen:
                    first_delta_yielded = True
                    yield StreamEvent(
                        type=StreamEventType.delta,
                        data={"delta": chunk},
                    )
                break
            except Exception:
                if first_delta_yielded:
                    raise
                attempt += 1
                if attempt > max_retries:
                    raise
                gen = StreamGenerator(
                    self._model_adapter,
                    msgs,
                    echo_text=echo,
                    streaming_enabled=streaming_enabled,
                    tool_schemas=tool_schemas,
                    route_role=preferred_role,
                )

        latency = int((datetime.now(UTC) - call_start).total_seconds() * 1000)
        self._model_call_count += 1

        resp = gen.response or ModelResponse(content="")
        resp.latency_ms = latency
        resp.provider = getattr(self._model_adapter, "provider", "") if self._model_adapter else ""

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
            error=None,
        )

        if not resp.tool_intents:
            legacy = self._detect_tool_intents(resp.content)
            if legacy:
                resp.tool_intents = ModelResponse.from_legacy_dicts(legacy)

        return resp

    @staticmethod
    def _detect_tool_intents(text: str) -> list[dict[str, object]]:
        """Parse tool intents from model output (legacy XML fallback)."""
        import re

        intents: list[dict[str, object]] = []
        for match in re.finditer(
            r'<tool_call>\s*{\s*"name"\s*:\s*"([^"]+)"[^}]*}\s*</tool_call>',
            text,
        ):
            raw = match.group(0)
            try:
                obj = json.loads(raw.replace("<tool_call>", "").replace("</tool_call>", ""))
                intents.append({"name": obj.get("name", ""), "arguments": obj.get("arguments", {})})
            except Exception:
                intents.append({"name": match.group(1), "arguments": {}})
        return intents

    def process_stream(
        self,
        event: RuntimeEvent,
        request_id: str = "",
        streaming_enabled: bool = True,
        max_retries: int = 2,
    ) -> Generator[StreamEvent, None, None]:
        """Full-turn streaming: yields StreamEvent objects.

        Generates delta events during model inference, tool_call events
        during capability dispatch, and ends with final or error.
        """
        trace, span = self._prepare_turn_setup(event, "process_stream_turn")

        meta_data: dict[str, object] = {
            "trace_id": trace.id,
            "session_id": event.session_id,
            "workspace_id": event.workspace_id,
        }
        channel = event.payload.get("channel", "") if event.payload else ""
        if channel:
            meta_data["channel"] = channel
        if request_id:
            meta_data["request_id"] = request_id
        yield StreamEvent(
            type=StreamEventType.metadata,
            data=meta_data,
            request_id=request_id,
            trace_id=trace.id,
        )

        try:
            ctx, text = self._run_pre_model_phase(event, trace)

            tool_schemas = self._get_tool_schemas(actor=event.actor_id)

            delta_gen = self._stream_generate_reply(
                event,
                text,
                trace,
                span,
                ctx=ctx,
                tool_schemas=tool_schemas,
                streaming_enabled=streaming_enabled,
                max_retries=max_retries,
            )
            try:
                while True:
                    ev = next(delta_gen)
                    ev.request_id = request_id
                    ev.trace_id = trace.id
                    yield ev
            except StopIteration as e:
                model_resp = e.value

            # Multi-round tool loop with streaming events
            self._transition(TurnState.planning_tool)
            tool_round = 0
            while model_resp.tool_intents and self._cap_reg and tool_round < self._max_tool_rounds:
                tool_round += 1
                yield StreamEvent(
                    type=StreamEventType.tool_call_started,
                    data={"tool_count": len(model_resp.tool_intents), "round": tool_round},
                    request_id=request_id,
                    trace_id=trace.id,
                )
                try:
                    model_resp = self._dispatch_tools(event, model_resp, trace, span)
                    from cogito_agent.trace.redaction import RedactionHelper as _RedactionHelper

                    _redactor = _RedactionHelper()
                    yield StreamEvent(
                        type=StreamEventType.tool_call_completed,
                        data={
                            "tool_results": [
                                {
                                    "tool": r.get("tool", ""),
                                    "summary": _redactor.redact(str(r.get("summary", ""))[:100]),
                                }
                                for r in self._tool_results
                            ],
                            "round": tool_round,
                        },
                        request_id=request_id,
                        trace_id=trace.id,
                    )
                except ApprovalRequiredError as exc:
                    yield StreamEvent(
                        type=StreamEventType.approval_required,
                        data={
                            "approval_id": exc.approval_id,
                            "trace_id": trace.id,
                            "summary": "Approval required",
                        },
                        request_id=request_id,
                        trace_id=trace.id,
                    )
                    self._audit.log(
                        actor_id=event.actor_id,
                        action="turn_approval_required",
                        resource="session",
                        workspace_id=event.workspace_id,
                        session_id=event.session_id,
                        trace_id=trace.id,
                        decision="require_approval",
                    )
                    self._cleanup_turn(
                        trace, span, state_value=TurnState.waiting_approval.value,
                    )
                    return

            if tool_round >= self._max_tool_rounds and model_resp.tool_intents:
                model_resp = ModelResponse(content=_TOOL_CHAIN_TERMINATED)

            _, output_text = self._run_after_turn(event, model_resp, trace, span)

            yield StreamEvent(
                type=StreamEventType.final,
                data={
                    "response": output_text,
                    "trace_id": trace.id,
                    "state": TurnState.completed.value,
                    "input_tokens": model_resp.input_tokens,
                    "output_tokens": model_resp.output_tokens,
                    "model": model_resp.model or "",
                    "provider": model_resp.provider or "",
                    "latency_ms": model_resp.latency_ms,
                },
                request_id=request_id,
                trace_id=trace.id,
            )

        except BudgetError as exc:
            self._safe_transition(self._sm, TurnState.failed)
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "error": {
                        "code": "BUDGET_EXCEEDED",
                        "message": str(exc),
                        "request_id": request_id,
                        "trace_id": trace.id,
                        "retryable": False,
                    },
                },
                request_id=request_id,
                trace_id=trace.id,
            )

        except PolicyDeniedError as exc:
            self._safe_transition(self._sm, TurnState.denied)
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "error": {
                        "code": "POLICY_DENIED",
                        "message": str(exc),
                        "request_id": request_id,
                        "trace_id": trace.id,
                        "retryable": False,
                    },
                },
                request_id=request_id,
                trace_id=trace.id,
            )

        except Exception as exc:
            self._safe_transition(self._sm, TurnState.failed)
            from cogito_agent.models.provider_errors import normalize_provider_error

            perr = normalize_provider_error(exc)
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "error": {
                        "code": perr.code.value,
                        "message": perr.safe_message,
                        "request_id": request_id,
                        "trace_id": trace.id,
                        "retryable": perr.retryable,
                    },
                },
                request_id=request_id,
                trace_id=trace.id,
            )

        self._cleanup_turn(trace, span, state_value=self._sm.state.value)

    def interrupt(self, event: RuntimeEvent) -> None:
        self._sm.transition(TurnState.interrupted)
        self._persistence.persist_interrupted_turn(
            event_json=event.model_dump_json(),
            turn_state=self._sm.state.value,
            model_call_count=self._model_call_count,
            tool_call_count=self._tool_call_count,
        )

    def resume(self, event: RuntimeEvent) -> TurnResult:
        self._sm.transition(TurnState.resuming)
        self._start_time = datetime.now(UTC)
        return self.process(event)

    # ── Queue-aware entry point ────────────────────────────────────────

    def process_from_queue(self, inbound: "InboundMessage") -> TurnResult:
        """Process an InboundMessage from the queue and return a TurnResult.

        Converts the queue message to a RuntimeEvent and delegates to
        ``process()``.  This is the single entry point the queue consumer
        (AgentLoop / DriftConsumer) should call.
        """
        event = self._inbound_to_event(inbound)
        return self.process(event)

    @staticmethod
    def _inbound_to_event(inbound: "InboundMessage") -> RuntimeEvent:
        """Convert an InboundMessage to a RuntimeEvent for ``process()``."""
        from cogito_agent.queue.message import InboundMessage as _IM

        source_map: dict[str, EventSource] = {
            "cli": EventSource.cli, "web": EventSource.api, "acp": EventSource.api,
        }
        source = source_map.get(inbound.channel, EventSource.api)
        payload: dict[str, object] = {"text": inbound.content}
        if inbound.media:
            payload["content"] = inbound.media
        return RuntimeEvent(
            id=str(uuid.uuid4()),
            workspace_id=inbound.workspace_id,
            session_id=inbound.session_id,
            actor_id=str(inbound.metadata.get("actor_id", "user")),
            source=source,
            type=EventType.user_message,
            payload=payload,
        )

    def _transition(self, target: TurnState) -> None:
        self._sm.transition(target)

    def _check_budget_model(self) -> None:
        if not self._budget.can_call_model(self._model_call_count):
            raise BudgetError(
                f"Model call budget exceeded "
                f"({self._model_call_count}/{self._budget.max_model_calls})"
            )
        elapsed = (datetime.now(UTC) - (self._start_time or datetime.now(UTC))).total_seconds()
        if elapsed > self._budget.max_wall_time_seconds:
            raise BudgetError(
                f"Wall clock budget exceeded "
                f"({elapsed:.1f}s > {self._budget.max_wall_time_seconds}s)"
            )

    def _check_budget_tool(self) -> None:
        if not self._budget.can_call_tool(self._tool_call_count):
            raise BudgetError(
                f"Tool call budget exceeded ({self._tool_call_count}/{self._budget.max_tool_calls})"
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
                actor_id=event.actor_id,
                action="call_model",
                resource="model_provider",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                decision="deny",
                reason=decision.reason,
            )
            raise PolicyDeniedError(f"Model call denied: {decision.reason}")

    def _check_memory_context_guard(
        self, event: RuntimeEvent, messages_raw: list[dict[str, object]]
    ) -> None:
        """Block the turn if consolidation backlog is too large."""
        if self._consolidation_service is None:
            return
        backlog = self._consolidation_service.consolidation_backlog(
            event.workspace_id, len(messages_raw)
        )
        if backlog > _CONSOLIDATION_GUARD_THRESHOLD:
            msg = (
                f"Memory consolidation backlog ({backlog} messages) exceeds "
                f"guard threshold. Please wait for background consolidation "
                f"to catch up before continuing the conversation."
            )
            raise RuntimeError(msg)

    def _build_context(
        self,
        event: RuntimeEvent,
        trace_id: str = "",
    ) -> list[ContextItem]:
        messages_raw = self._persistence.list_messages(event.session_id, event.workspace_id)
        # Memory context guard: check consolidation backlog before building context
        self._check_memory_context_guard(event, messages_raw)
        recent_messages: list[dict[str, object]] = [dict(m) for m in messages_raw[-6:]]
        text_projection = str(event.payload.get("text", "") or "")
        self._load_context_memories(event, recent_messages, text_projection, trace_id)
        ctx_items = self._ctx_engine.build(
            recent_messages=recent_messages,
            memories=self._current_memories,
            current_message=text_projection,
            trace_id=trace_id,
            workspace_id=event.workspace_id,
            session_summary=self._persistence.get_latest_summary(
                event.workspace_id, event.session_id
            ),
            workspace_path=self._workspace_path,
        )
        raw = event.payload.get("content", [])
        self._extra_content = raw if isinstance(raw, list) else []
        self._current_ctx = ctx_items
        return ctx_items

    def _load_context_memories(
        self,
        event: RuntimeEvent,
        recent_messages: list[dict[str, object]],
        current_message: str,
        trace_id: str,
    ) -> None:
        """Load memories via Retrieval V2, building MemoryRecallResult."""
        self._current_recall_result = None
        memories: list[dict[str, object]] = []

        if self._memory_retrieval_service is not None:
            try:
                query = current_message
                if not query.strip():
                    content_raw = event.payload.get("content", [])
                    if isinstance(content_raw, list):
                        texts = [
                            str(c.get("text", ""))
                            for c in content_raw
                            if isinstance(c, dict) and c.get("text")
                        ]
                        query = " ".join(texts) if texts else ""

                user_msgs = [
                    str(m.get("content", "")) for m in recent_messages if m.get("role") == "user"
                ]

                session_summary = self._persistence.get_latest_summary(
                    event.workspace_id,
                    event.session_id,
                )
                summary_text = str(session_summary.get("summary", "")) if session_summary else ""

                qctx = self._query_builder_for_retrieval.build(
                    current_message=query,
                    recent_user_messages=user_msgs,
                    session_topic_summary=summary_text,
                    workspace_id=event.workspace_id,
                    session_id=event.session_id,
                )
                qctx.trace_id = trace_id

                recall_result = self._memory_retrieval_service.recall(
                    query_context=qctx,
                    limit=5,
                    min_score=0.35,
                )
                self._current_recall_result = recall_result
                self._current_retrieval_trace_id = recall_result.trace_id

                memories_from_recall: list[dict[str, object]] = []
                for mem in recall_result.resident_memories:
                    entry = dict(mem)
                    entry.setdefault("retrieval_source", "resident")
                    memories_from_recall.append(entry)
                for mem in recall_result.dynamic_memories:
                    entry = dict(mem)
                    entry.setdefault("retrieval_source", "dynamic")
                    memories_from_recall.append(entry)
                memories = memories_from_recall
            except Exception:
                logger.exception("Retrieval V2 failed")
                memories = []

        self._current_memories = memories

    def _update_session_summary(self, event: RuntimeEvent) -> None:
        try:
            self._persistence.update_summary(event.workspace_id, event.session_id)

            # Sync SESSION_SUMMARY.md view
            if self._workspace_path:
                try:
                    summary = self._persistence.get_latest_summary(
                        event.workspace_id,
                        event.session_id,
                    )
                    if summary and summary.get("summary"):
                        from cogito_agent.memory.file_io import atomic_write_memory_file

                        content = (
                            "# Session Summary\n\n"
                            f"{summary['summary']}\n"
                        )
                        atomic_write_memory_file(
                            self._workspace_path,
                            "SESSION_SUMMARY.md",
                            content,
                        )
                except Exception:
                    logger.debug("SESSION_SUMMARY.md sync failed (non-fatal)")
        except Exception:
            # Compression is a derived optimization and must not fail a turn.
            return

    def _build_model_messages(
        self,
        event: RuntimeEvent,
        message: str,
        trace: object,
        ctx: list[ContextItem] | None = None,
    ) -> list[dict[str, object]]:
        if ctx is None:
            t_id = str(getattr(trace, "id", ""))
            ctx = self._build_context(event, trace_id=t_id)
        extra_content = self._get_extra_content(event)
        span = getattr(trace, "_current_span", None) or trace

        # Resolve attachment references to data URIs for native vision models
        resolved_content = self._resolve_attachment_content(extra_content, event.workspace_id)

        # Collect vision observations context for attachments
        vision_context = self._build_vision_context(
            resolved_content,
            event.workspace_id,
            event.session_id,
        )

        should_delegate_vision = has_image(resolved_content) and not self._supports_vision()
        if should_delegate_vision:
            text_only_content, text_only_message = self._run_vision_pipeline(
                resolved_content,
                message,
                trace,
                span,
                event=event,
            )
            return self._prompt_builder.build(
                ctx_items=ctx,
                current_message=text_only_message,
                tool_results=self._tool_results,
                extra_content=text_only_content,
                vision_context=vision_context,
            )

        return self._prompt_builder.build(
            ctx_items=ctx,
            current_message=message,
            tool_results=self._tool_results,
            extra_content=resolved_content if has_image(resolved_content) else resolved_content,
            vision_context=vision_context,
        )

    def _resolve_attachment_content(
        self,
        extra_content: list[ContentPart],
        workspace_id: str,
    ) -> list[ContentPart]:
        """Delegate to VisionPipeline."""
        pipeline = self._vision_pipeline
        if pipeline is not None:
            return pipeline.resolve_attachments(extra_content, workspace_id)

        from .vision_pipeline import VisionPipeline

        return VisionPipeline(
            vision_service=self._vision_service,
        ).resolve_attachments(extra_content, workspace_id)

    def _build_vision_context(
        self,
        extra_content: list[ContentPart],
        workspace_id: str,
        session_id: str,
    ) -> str:
        """Delegate to VisionPipeline."""
        pipeline = self._vision_pipeline
        if pipeline is not None:
            return pipeline.build_vision_context(extra_content, workspace_id, session_id)
        return ""

    def _supports_vision(self) -> bool:
        """Delegate to VisionPipeline."""
        pipeline = self._vision_pipeline
        if pipeline is not None:
            return pipeline.supports_vision()
        return False

    def _get_extra_content(self, event: RuntimeEvent) -> list[ContentPart]:
        raw = event.payload.get("content", [])
        if isinstance(raw, list):
            return normalize_content(raw)
        return []

    def _generate_reply(
        self,
        event: RuntimeEvent,
        message: str,
        trace: object,
        span: object,
        ctx: list[ContextItem] | None = None,
        max_retries: int = 2,
    ) -> ModelResponse:
        extra_content = self._get_extra_content(event)
        has_multimodal = bool(extra_content) or bool(event.payload.get("content"))
        has_text = bool(message.strip())
        if not has_text and not has_multimodal:
            return ModelResponse(content="I didn't receive any message.")
        if self._model_adapter is None:
            text = message or " "
            return ModelResponse(content=f"You said: {text}")
        msgs = self._build_model_messages(event, message, trace, ctx=ctx)
        self._bind_route_observer(event, trace, span)
        tool_schemas = self._get_tool_schemas(actor=event.actor_id)

        kwargs: dict[str, object] = {}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        preferred_role = str(event.payload.get("_preferred_role", "") or "")
        if preferred_role:
            kwargs["_route_role"] = preferred_role

        call_start = datetime.now(UTC)
        resp: ModelResponse = self._retry_with_backoff(
            lambda: self._model_adapter.chat(msgs, **kwargs),
            max_retries=max_retries,
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

        return resp

    def _bind_route_observer(self, event: RuntimeEvent, trace: object, parent_span: object) -> None:
        """Attach turn-scoped routing telemetry through an optional protocol hook."""
        if self._model_adapter is None:
            return
        setter = getattr(self._model_adapter, "set_route_observer", None)
        if not callable(setter):
            return

        trace_id = str(getattr(trace, "id", ""))
        parent_span_id = str(getattr(parent_span, "id", "")) or None

        def observe(route_event: ModelRouteEvent) -> None:
            candidate = route_event.candidate
            candidate_id = candidate.id if candidate is not None else ""
            selected = route_event.decision.selected
            details: dict[str, object] = {
                "event_type": route_event.type.value,
                "selected": selected.id if selected is not None else None,
                "fallback_order": [item.id for item in route_event.decision.fallback_order],
                "exclusions": [
                    exclusion.model_dump() for exclusion in route_event.decision.exclusions
                ],
                "candidate": candidate_id or None,
                "attempt_index": route_event.attempt_index,
                "remaining_candidates": route_event.remaining_candidates,
            }
            if route_event.error:
                details["error"] = route_event.error

            if route_event.type == ModelRouteEventType.decision:
                action = "model_route_decided"
                decision = "allow" if selected is not None else "deny"
                span_name = "model.route"
                span_status = "completed" if selected is not None else "failed"
                reason = route_event.decision.reason
            elif route_event.type == ModelRouteEventType.attempt_failed:
                action = "model_route_attempt_failed"
                decision = "fallback" if route_event.remaining_candidates else "fail"
                span_name = "model.route.attempt"
                span_status = "failed"
                reason = "model candidate failed"
            else:
                action = "model_route_selected"
                decision = "allow"
                span_name = "model.route.attempt"
                span_status = "completed"
                reason = "model candidate completed"

            route_span = self._tracer.create_span(
                trace_id,
                span_name,
                SpanKind.model,
                parent_span_id=parent_span_id,
            )
            self._tracer.end_span(route_span, span_status)
            self._audit.log(
                actor_id=event.actor_id,
                action=action,
                resource="model_router",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                trace_id=trace_id,
                decision=decision,
                reason=reason,
                details=json.dumps(details, ensure_ascii=False, sort_keys=True),
            )

        setter(observe)

    def _dispatch_tools(
        self,
        event: RuntimeEvent,
        resp: ModelResponse,
        trace: object,
        span: object,
    ) -> ModelResponse:
        collected_results: list[dict[str, object]] = []
        for intent in resp.tool_intents:
            capability_name = intent.capability_name
            if not capability_name:
                continue

            # Some providers (DeepSeek) reject dots in function names;
            # the adapter sanitizes with _ -> . / : reverse mapping.
            if self._cap_reg is not None:
                resolved = self._resolve_tool_name(capability_name)
                if resolved is not None:
                    capability_name = resolved

            self._check_budget_tool()
            args = dict(intent.arguments) if intent.arguments else {}

            # Inject current workspace/trace context for vision and meme services
            if self._vision_service is not None:
                self._vision_service.set_current_context(
                    workspace_id=event.workspace_id,
                    trace_id=str(getattr(trace, "id", "")),
                )
            if self._meme_service is not None:
                self._meme_service.set_current_context(
                    workspace_id=event.workspace_id,
                    trace_id=str(getattr(trace, "id", "")),
                )
            if self._memory_service is not None:
                self._memory_service.set_current_context(
                    workspace_id=event.workspace_id,
                    trace_id=str(getattr(trace, "id", "")),
                )

            if self._cap_executor is None:
                collected_results.append(
                    {
                        "tool": capability_name,
                        "error": "Capability executor unavailable",
                    }
                )
                continue
            execution = self._cap_executor.execute(
                CapabilityExecutionRequest(
                    capability_name=capability_name,
                    arguments=args,
                    actor_id=event.actor_id,
                    source=event.source.value,
                    workspace_id=event.workspace_id,
                    session_id=event.session_id,
                    trace_id=str(getattr(trace, "id", "")),
                    span_id=str(getattr(span, "id", "")),
                    tool_call_id=intent.tool_call_id,
                )
            )
            if execution.status == "approval_required":
                raise ApprovalRequiredError(
                    f"Approval required for {capability_name}",
                    approval_id=execution.approval_id,
                )
            if execution.status in {"denied", "not_found"}:
                collected_results.append(
                    {
                        "tool": capability_name,
                        "error": f"Denied: {execution.reason}",
                    }
                )
                continue
            tool_result = execution.tool_result
            self._tool_call_count += 1
            if execution.status == "error":
                error_message = (
                    tool_result.error
                    if tool_result is not None and tool_result.error
                    else "Capability execution failed"
                )
                raise RuntimeError(error_message)

            summary = tool_result.summary if tool_result else ""
            error = tool_result.error if tool_result else None
            status = "ok" if tool_result and tool_result.status == "ok" else "error"

            collected_results.append(
                {
                    "tool": capability_name,
                    "summary": summary,
                    "error": error,
                }
            )
            tr_entry: dict[str, object] = {
                "tool": capability_name,
                "summary": summary,
                "status": status,
            }
            # Propagate image data from tool result for multimodal routing
            if tool_result and isinstance(getattr(tool_result, "data", None), dict):
                tr_data = tool_result.data
                if "image_b64" in tr_data:
                    tr_entry["image_b64"] = tr_data["image_b64"]
                    tr_entry["mime_type"] = tr_data.get("mime_type", "image/png")
            self._tool_results.append(tr_entry)

        tools_invoked = any(
            r.get("error") is None or "Denied" not in str(r.get("error", ""))
            for r in collected_results
        )
        if collected_results and self._model_adapter and tools_invoked:
            event_with_text = RuntimeEvent(
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                actor_id=event.actor_id,
                source=event.source,
                type=EventType.tool_result,
                payload={"text": ""},
            )
            follow_up_msgs = self._build_model_messages(
                event_with_text,
                "",
                trace,
            )
            follow_up_msgs.append(
                {
                    "role": "assistant",
                    "content": str(resp.content),
                }
            )
            for r in collected_results:
                raw = str(r.get("summary", "") or r.get("error", ""))
                tool_call_id = intent.tool_call_id if hasattr(intent, "tool_call_id") else ""
                follow_up_msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": wrap_untrusted(raw),
                    }
                )
            tool_schemas = self._get_tool_schemas(actor=event.actor_id)
            kwargs: dict[str, object] = {}
            if tool_schemas:
                kwargs["tools"] = tool_schemas
            follow_up = self._model_adapter.chat(follow_up_msgs, **kwargs)
            self._model_call_count += 1
            return follow_up

        return resp

    def _compose_result(
        self,
        event: RuntimeEvent,
        resp: ModelResponse,
        trace: object,
        span: object,
    ) -> ComposedResult:
        return self._result_composer.compose(
            resp,
            sources=self._sources,
            tool_summaries=self._tool_results,
        )

    def _consolidate(self, event: RuntimeEvent) -> None:
        if not self._consolidation_service:
            return
        try:
            messages = self._persistence.list_messages(
                event.session_id, event.workspace_id,
            )
            dict_messages = [dict(m) for m in messages]

            # Step 1: basic after_turn (Recent Turns, journal, async enqueue)
            self._consolidation_service.after_turn(
                messages=dict_messages,
                workspace_id=event.workspace_id,
                session_id=event.session_id,
            )

            # Step 2: synchronous LLM extraction + RECENT_CONTEXT compression
            prev_count = len(dict_messages) - (
                self._consolidation_service._consolidation_min_new
            )
            if prev_count > 0:
                self._consolidation_service._extract_and_write(
                    messages=dict_messages,
                    prev_count=prev_count,
                    workspace_id=event.workspace_id,
                    session_id=event.session_id,
                )

            # Step 3: trim old messages (sliding window)
            trim_point = self._consolidation_service.get_trim_point(
                event.workspace_id, len(dict_messages)
            )
            if trim_point > 0:
                self._persistence.trim_messages(
                    event.session_id, event.workspace_id, trim_point
                )
        except Exception:
            logger.exception("Post-turn consolidation failed")

    def _persist_user_message(self, event: RuntimeEvent) -> None:
        raw = event.payload.get("text", "")
        user_text = str(raw) if raw is not None else ""
        content_raw = event.payload.get("content", [])
        has_multimodal = bool(content_raw) and (
            not user_text.strip()
            or any(
                isinstance(c, dict) and c.get("type") in ("image", "file")
                for c in (content_raw if isinstance(content_raw, list) else [])
            )
        )
        persist_text = user_text or "[multimodal message]" if has_multimodal else (user_text or "")
        if persist_text.strip():
            mid = str(uuid.uuid4())
            title = user_text[:80] if user_text.strip() else "[multimodal]"
            self._persistence.persist_user_message(
                message_id=mid,
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                content=persist_text,
                title_if_empty=title,
            )

    def _persist(self, event: RuntimeEvent, output: str, trace_id: str = "", model_resp: ModelResponse | None = None) -> None:
        mid = str(uuid.uuid4())
        metadata: dict[str, object] = {}
        if trace_id:
            metadata["trace_id"] = trace_id
        if model_resp:
            if model_resp.input_tokens:
                metadata["input_tokens"] = model_resp.input_tokens
            if model_resp.output_tokens:
                metadata["output_tokens"] = model_resp.output_tokens
            if model_resp.model:
                metadata["model"] = model_resp.model
            if model_resp.provider:
                metadata["provider"] = model_resp.provider
            if model_resp.latency_ms:
                metadata["latency_ms"] = model_resp.latency_ms
        self._persistence.persist_assistant_message(
            message_id=mid,
            workspace_id=event.workspace_id,
            session_id=event.session_id,
            content=output,
            trace_id=trace_id,
            metadata=metadata,
        )

    # ── Turn pipeline shared helpers ─────────────────────────────────────────
    # These methods extract the identical logic that was previously duplicated
    # between process() and process_stream(). Each caller wraps them with its own
    # return / yield formatting.

    @staticmethod
    def _safe_transition(sm: TurnStateMachine, target: TurnState) -> None:
        """Transition state, ignoring invalid transitions."""
        try:
            sm.transition(target)
        except ValueError:
            pass

    def _prepare_turn_setup(
        self, event: RuntimeEvent, span_name: str = "process_turn"
    ) -> tuple[object, object]:
        """Reset state, create trace+span, track presence.

        Shared prologue for *process* and *process_stream*.
        """
        terminal = {
            TurnState.completed,
            TurnState.failed,
            TurnState.denied,
            TurnState.cancelled,
            TurnState.budget_exceeded,
        }
        if self._sm.state in terminal:
            self._sm._state = TurnState.received

        if self._presence is not None and event.type in (
            EventType.user_message, EventType.user_command,
        ):
            self._presence.touch(
                session_key=event.session_id or "default",
                channel=event.source.value if hasattr(event.source, "value") else str(event.source),
            )

        trace = self._tracer.create_trace(
            workspace_id=event.workspace_id,
            root_event_id=event.id,
            session_id=event.session_id,
        )
        span = self._tracer.create_span(trace.id, span_name, SpanKind.runtime)
        span.input_summary = f"event={event.type.value}, actor={event.actor_id}"
        self._start_time = datetime.now(UTC)
        return trace, span

    def _run_pre_model_phase(
        self, event: RuntimeEvent, trace: object,
    ) -> tuple[list[ContextItem], str]:
        """Session loading → context building → budget & policy checks.

        Shared pre-model-call phase used by both *process* and *process_stream*.
        Returns the built context items and the extracted user text.
        """
        self._sm.transition(TurnState.loading_session)
        self._persist_user_message(event)
        self._transition(TurnState.building_context)
        ctx = self._build_context(event, trace_id=trace.id)
        self._sources = [
            {"type": c.source_type, "id": c.source_id, "text": c.text}
            for c in ctx
            if isinstance(c, ContextItem) and c.included
        ]

        self._transition(TurnState.model_calling)
        self._check_budget_model()
        self._check_model_policy(event)
        raw_text = event.payload.get("text", "") if event.type == EventType.user_message else ""
        text = str(raw_text) if raw_text is not None else ""
        return ctx, text

    def _run_after_turn(
        self, event: RuntimeEvent, model_resp: ModelResponse, trace: object, span: object,
    ) -> tuple[ComposedResult, str]:
        """Result composition → persist → summary → consolidate → audit.

        Shared post-tool-loop phase.  Returns the composited result and rendered
        output text; the caller wraps these in a TurnResult or StreamEvent.final.
        """
        model_result = self._compose_result(event, model_resp, trace, span)
        output_text = model_result.render_text()

        self._transition(TurnState.composing_result)
        self._persist(event, output_text, trace.id, model_resp=model_resp)
        self._update_session_summary(event)
        self._consolidate(event)

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
        return model_result, output_text

    def _resolve_tool_name(self, name: str) -> str | None:
        """Resolve a sanitized tool name back to its original dotted form.

        Some providers (e.g. DeepSeek) reject dots/colons in function names.
        The adapter sanitizes ALL dots/colons to underscores.
        This method tries reverse mappings and checks against the capability registry.
        """
        if not name or "_" not in name or self._cap_reg is None:
            return None
        # Try: replace all _ with .  (most common: memory_store_candidate -> memory.store.candidate)
        for sep in (".", ":"):
            candidate = name.replace("_", sep)
            if candidate == name:
                continue
            if self._cap_reg.get_manifest(candidate) is not None:
                return candidate
        # Try replacing first _ only (memory_store -> memory.store)
        for sep in (".", ":"):
            idx = name.find("_")
            if idx < 0:
                continue
            candidate = name[:idx] + sep + name[idx + 1:]
            if self._cap_reg.get_manifest(candidate) is not None:
                return candidate
        return None

    def _cleanup_turn(
        self,
        trace: object,
        span: object,
        *,
        state_value: str,
        error: str | None = None,
    ) -> None:
        """Close span and trace, setting the output summary."""
        self._tracer.end_span(span)
        self._tracer.end_trace(trace)
        summary = f"state={state_value}"
        if error:
            summary += f", error={error}"
        span.output_summary = summary
