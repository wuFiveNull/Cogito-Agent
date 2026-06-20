from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.schemas import (
    filter_available_tools,
    manifest_to_tool_schema,
)
from cogito_agent.context import (
    ContextEngine,
    ContextItem,
    PromptBuilder,
    SessionCompressionService,
)
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.memory import CandidateExtractor, MemoryRetriever
from cogito_agent.models import (
    ModelAdapter,
    ModelResponse,
    ModelRouteEvent,
    ModelRouteEventType,
    StreamGenerator,
    ToolIntent,
)
from cogito_agent.models.messages import (
    ContentPart,
    ImagePart,
    TextPart,
    has_image,
    normalize_content,
)
from cogito_agent.models.messages import (
    extract_text as _extract_text_from_parts,
)
from cogito_agent.shared import (
    DecisionType,
    EventType,
    PolicyRequest,
    RuntimeEvent,
    SpanKind,
    TurnState,
    TurnStateMachine,
)
from cogito_agent.shared.safety import wrap_untrusted
from cogito_agent.shared.stream_events import StreamEvent, StreamEventType
from cogito_agent.storage import Database, MessageRepository, SessionRepository
from cogito_agent.storage.repositories import ApprovalRepository, AttachmentRepository, VisionObservationRepository
from cogito_agent.trace import SourceLineage, Tracer

from cogito_agent.media.vision_service import VisionObservationService

from .budget import TurnBudget
from .multimodal import MultimodalCoordinator
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
        db: Database,
        budget: TurnBudget | None = None,
        model_adapter: ModelAdapter | None = None,
        capability_registry: CapabilityRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        context_engine: ContextEngine | None = None,
        memory_retriever: MemoryRetriever | None = None,
        candidate_extractor: CandidateExtractor | None = None,
        max_tool_rounds: int = 3,
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
        self._max_tool_rounds = max_tool_rounds
        self._prompt_builder = PromptBuilder()
        self._result_composer = ResultComposer()
        self._compression = SessionCompressionService(db)
        self._extra_content: list[ContentPart] = []
        self._multimodal_coordinator: MultimodalCoordinator | None = None
        self._vision_service: VisionObservationService | None = None
        self._meme_service: Any = None

    def set_vision_service(self, service: VisionObservationService) -> None:
        self._vision_service = service

    def set_meme_service(self, service: Any) -> None:
        self._meme_service = service

    def _run_vision_pipeline(
        self,
        extra_content: list[ContentPart],
        user_text: str,
        trace: object,
        span: object,
        event: RuntimeEvent | None = None,
    ) -> tuple[list[ContentPart], str]:
        """If images present in content, run vision pipeline and return modified content.

        Returns:
            Tuple of (modified_content, user_text_without_images).
            If no images, content and text are returned unchanged.
        """
        if not has_image(extra_content) or self._model_adapter is None:
            return extra_content, user_text

        image_parts = [p for p in extra_content if isinstance(p, ImagePart)]
        text_parts = [p for p in extra_content if not isinstance(p, ImagePart)]
        primary_text = _extract_text_from_parts(text_parts) or user_text  # type: ignore[arg-type]

        # If vision service is available with its own adapter, use it via inspect_image
        if self._vision_service is not None and self._vision_service.has_vision_capability:
            try:
                self._vision_service.set_current_context(
                    workspace_id=(event.workspace_id if event else ""),
                    trace_id=str(getattr(trace, "id", "")),
                )
                results: list[str] = []
                trace_id = str(getattr(trace, "id", ""))
                for img_part in image_parts:
                    att_id = getattr(img_part, "attachment_id", None) or ""
                    if not att_id:
                        continue
                    result = self._vision_service.inspect_image(
                        attachment_id=att_id,
                        prompt=primary_text or "Describe this image",
                        workspace_id=(event.workspace_id if event else ""),
                        trace_id=trace_id,
                    )
                    if result:
                        results.append(result)

                if results:
                    combined = "\n\n".join(results)
                    call_id = f"vision_{uuid.uuid4().hex[:12]}"
                    self._tool_results.append({
                        "tool": "vision.observe",
                        "summary": combined[:500],
                        "status": "ok",
                        "tool_call_id": call_id,
                    })
                    return text_parts, primary_text  # type: ignore[return-value]
            except Exception as exc:
                logger.warning("Vision service pipeline failed, falling back: %s", exc)

        try:
            call_start = datetime.now(UTC)
            vision_msgs = self._build_vision_messages(image_parts, primary_text)
            if event is not None:
                self._bind_route_observer(event, trace, span)
            vision_resp = self._model_adapter.chat(
                vision_msgs,
                _route_role="vision_worker",
                _route_task_kind="vision_understanding",
            )
            vision_latency = int((datetime.now(UTC) - call_start).total_seconds() * 1000)

            self._model_call_count += 1
            self._tracer.log_model_call(
                trace_id=str(getattr(trace, "id", "")),
                span_id=str(getattr(span, "id", "")),
                provider=vision_resp.provider,
                model=vision_resp.model,
                input_token_count=vision_resp.input_tokens,
                output_token_count=vision_resp.output_tokens,
                prompt_summary=f"vision analysis ({len(image_parts)} images)",
                response_summary=vision_resp.content[:200] if vision_resp.content else "",
                latency_ms=vision_latency,
                stop_reason=vision_resp.stop_reason,
                error=vision_resp.error,
            )

            if vision_resp.error:
                raise RuntimeError(f"Vision model error: {vision_resp.error}")

            from cogito_agent.models.vision import VisionObservation, _extract_json, _repair_json

            parsed = _extract_json(vision_resp.content)
            if parsed is None:
                parsed = _repair_json(vision_resp.content)
            if parsed is None:
                raise RuntimeError(
                    f"Vision model returned unparseable JSON: {vision_resp.content[:200]}"
                )
            observation = VisionObservation.model_validate(parsed)

            call_id = f"vision_{uuid.uuid4().hex[:12]}"
            self._tool_results.append({
                "tool": "vision.observe",
                "summary": observation.model_dump_json(),
                "status": "ok",
                "tool_call_id": call_id,
            })

            logger.info(
                "Vision pipeline succeeded: %s via %s (%d images, %dms)",
                observation.summary[:80], vision_resp.model,
                len(image_parts), vision_latency,
            )
            return text_parts, primary_text  # type: ignore[return-value]

        except Exception as exc:
            logger.error("Vision pipeline failed: %s", exc)
            raise RuntimeError(
                f"Vision analysis failed: {exc}. "
                f"Cannot proceed with primary model - images cannot be directly processed."
            ) from exc

    @staticmethod
    def _build_vision_messages(
        image_parts: list[ImagePart], instruction: str,
    ) -> list[dict[str, object]]:
        """Build legacy dict messages for vision model."""
        from cogito_agent.models.messages import ChatMessage, MessageRole

        vision_prompt = (
            "You are a vision analysis model. Analyze the provided image(s) and "
            "output a structured JSON observation. Do NOT include markdown fences "
            "or extra commentary. Output ONLY valid JSON matching this schema:\n"
            '{"summary": "...", "ocr_text": [...], "objects": [...], '
            '"ui_elements": [...], '
            '"spatial_relations": [...], "uncertainties": [...]}'
        )
        sys_msg = ChatMessage(
            role=MessageRole.system,
            content=[TextPart(text=vision_prompt)],
        )
        user_msg = ChatMessage(
            role=MessageRole.user,
            content=[*image_parts],
        )
        msgs: list[dict[str, object]] = [
            sys_msg.to_legacy_dict(),
            user_msg.to_legacy_dict(),
        ]
        if instruction.strip():
            inst_msg = ChatMessage(
                role=MessageRole.user,
                content=[TextPart(text=instruction)],
            )
            msgs.append(inst_msg.to_legacy_dict())
        return msgs

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

    def _get_tool_schemas(self, actor: str = "assistant") -> list[dict[str, object]]:
        if not self._cap_reg:
            return []
        manifests = self._cap_reg.list_tools()
        available = filter_available_tools(manifests, actor=actor)
        return [manifest_to_tool_schema(m) for m in available]

    def process(self, event: RuntimeEvent) -> TurnResult:
        terminal = {TurnState.completed, TurnState.failed, TurnState.denied,
                    TurnState.cancelled, TurnState.budget_exceeded}
        if self._sm.state in terminal:
            self._sm._state = TurnState.received

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

            self._transition(TurnState.model_calling)
            self._check_budget_model()
            self._check_model_policy(event)
            raw_text = (
                event.payload.get("text", "")
                if event.type == EventType.user_message
                else ""
            )
            text = str(raw_text) if raw_text is not None else ""
            model_resp = self._generate_reply(event, text, trace, span)

            self._transition(TurnState.planning_tool)

            # Multi-round tool loop
            tool_round = 0
            while (
                model_resp.tool_intents
                and self._cap_reg
                and tool_round < self._max_tool_rounds
            ):
                tool_round += 1
                model_resp = self._dispatch_tools(event, model_resp, trace, span)
                # Budget check is handled inside _dispatch_tools per-tool

            if tool_round >= self._max_tool_rounds and model_resp.tool_intents:
                model_resp = ModelResponse(
                    content="Tool chain terminated: maximum tool rounds reached. "
                            "Results from completed tools have been applied."
                )

            model_result = self._compose_result(event, model_resp, trace, span)
            tool_summaries = list(self._tool_results)

            self._transition(TurnState.composing_result)
            self._transition(TurnState.extracting_memory)
            output_text = model_result.render_text()
            self._persist_user_message(event)
            self._persist(event, output_text, trace.id)
            self._update_session_summary(event)
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
                trace_id=trace.id,
                composed_result=model_result,
            )

        except BudgetError as exc:
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
            result = TurnResult(
                state=TurnState.failed, error=str(exc), output=str(exc),
                trace_id=trace.id,
            )

        except PolicyDeniedError as exc:
            try:
                self._sm.transition(TurnState.denied)
            except ValueError:
                pass
            result = TurnResult(
                state=TurnState.denied, error=str(exc), trace_id=trace.id,
            )

        except ApprovalRequiredError as exc:
            try:
                self._sm.transition(TurnState.waiting_approval)
            except ValueError:
                pass
            result = TurnResult(
                state=TurnState.waiting_approval,
                approval_pending=True,
                approval_id=exc.approval_id,
                error=str(exc),
                trace_id=trace.id,
            )

        except Exception as exc:
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
            error_msg = str(exc)
            result = TurnResult(
                state=TurnState.failed, error=error_msg, trace_id=trace.id,
            )

        self._tracer.end_span(span)
        self._tracer.end_trace(trace)
        span.output_summary = f"state={result.state.value}, error={result.error}"
        return result

    def _stream_generate_reply(
        self, event: RuntimeEvent, message: str,
        trace: object, span: object,
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
        gen = StreamGenerator(self._model_adapter, msgs, echo_text=echo,
                              streaming_enabled=streaming_enabled,
                              tool_schemas=tool_schemas,
                              route_role=preferred_role)

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
                gen = StreamGenerator(self._model_adapter, msgs, echo_text=echo,
                                      streaming_enabled=streaming_enabled,
                                      tool_schemas=tool_schemas,
                                      route_role=preferred_role)

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
        self, event: RuntimeEvent, request_id: str = "",
        streaming_enabled: bool = True,
        max_retries: int = 2,
    ) -> Generator[StreamEvent, None, None]:
        """Full-turn streaming: yields StreamEvent objects.

        Generates delta events during model inference, tool_call events
        during capability dispatch, and ends with final or error.
        """
        terminal = {TurnState.completed, TurnState.failed, TurnState.denied,
                    TurnState.cancelled, TurnState.budget_exceeded}
        if self._sm.state in terminal:
            self._sm._state = TurnState.received

        trace = self._tracer.create_trace(
            workspace_id=event.workspace_id,
            root_event_id=event.id,
            session_id=event.session_id,
        )
        span = self._tracer.create_span(trace.id, "process_stream_turn", SpanKind.runtime)
        span.input_summary = f"event={event.type.value}, actor={event.actor_id}, stream"
        self._start_time = datetime.now(UTC)

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
            self._sm.transition(TurnState.loading_session)
            self._transition(TurnState.building_context)
            ctx = self._build_context(event)
            self._sources = [
                {"type": c.source_type, "id": c.source_id, "text": c.text}
                for c in ctx if isinstance(c, ContextItem) and c.included
            ]

            self._transition(TurnState.model_calling)
            self._check_budget_model()
            self._check_model_policy(event)
            raw_text = (
                event.payload.get("text", "")
                if event.type == EventType.user_message
                else ""
            )
            text = str(raw_text) if raw_text is not None else ""

            tool_schemas = self._get_tool_schemas(actor=event.actor_id)

            delta_gen = self._stream_generate_reply(
                event, text, trace, span,
                ctx=ctx, tool_schemas=tool_schemas,
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

            self._transition(TurnState.planning_tool)

            tool_round = 0
            while (
                model_resp.tool_intents
                and self._cap_reg
                and tool_round < self._max_tool_rounds
            ):
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
                                {"tool": r.get("tool", ""),
                                 "summary": _redactor.redact(str(r.get("summary", ""))[:100])}
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
                    self._tracer.end_span(span)
                    self._tracer.end_trace(trace)
                    span.output_summary = "state=waiting_approval"
                    self._audit.log(
                        actor_id=event.actor_id, action="turn_approval_required",
                        resource="session",
                        workspace_id=event.workspace_id,
                        session_id=event.session_id,
                        trace_id=trace.id,
                        decision="require_approval",
                    )
                    return

            if tool_round >= self._max_tool_rounds and model_resp.tool_intents:
                model_resp = ModelResponse(
                    content="Tool chain terminated: maximum tool rounds reached. "
                            "Results from completed tools have been applied."
                )

            model_result = self._compose_result(event, model_resp, trace, span)
            output_text = model_result.render_text()

            self._transition(TurnState.composing_result)
            self._transition(TurnState.extracting_memory)
            self._persist_user_message(event)
            self._persist(event, output_text, trace.id)
            self._update_session_summary(event)
            self._candidate_extract(event, output_text)

            self._audit.log(
                actor_id=event.actor_id, action="turn_completed",
                resource="session",
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                trace_id=trace.id,
                decision="allow",
            )
            self._sm.transition(TurnState.completed)

            yield StreamEvent(
                type=StreamEventType.final,
                data={
                    "response": output_text,
                    "trace_id": trace.id,
                    "state": TurnState.completed.value,
                },
                request_id=request_id,
                trace_id=trace.id,
            )

        except BudgetError as exc:
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
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
            try:
                self._sm.transition(TurnState.denied)
            except ValueError:
                pass
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
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
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

        self._tracer.end_span(span)
        self._tracer.end_trace(trace)
        span.output_summary = f"state={self._sm.state.value}"

    def interrupt(self, event: RuntimeEvent) -> None:
        self._sm.transition(TurnState.interrupted)
        self._db.connection.execute(
            "INSERT INTO interrupted_turns"
            " (event_json, turn_state, model_call_count, tool_call_count)"
            " VALUES (?, ?, ?, ?)",
            (
                event.model_dump_json(),
                self._sm.state.value,
                self._model_call_count,
                self._tool_call_count,
            ),
        )
        self._db.connection.commit()

    def resume(self, event: RuntimeEvent) -> TurnResult:
        self._sm.transition(TurnState.resuming)
        self._start_time = datetime.now(UTC)
        return self.process(event)

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
            event.session_id, event.workspace_id
        )
        recent_messages: list[dict[str, object]] = [
            dict(m) for m in messages_raw[-6:]
        ]
        memories: list[dict[str, object]] = []
        if self._mem_retriever:
            try:
                raw = event.payload.get("text", "")
                query = str(raw) if raw is not None else ""
                if not query.strip():
                    content_raw = event.payload.get("content", [])
                    if isinstance(content_raw, list):
                        text_from_content = " ".join(
                            str(c.get("text", ""))
                            for c in content_raw
                            if isinstance(c, dict) and c.get("text")
                        )
                        query = text_from_content if text_from_content.strip() else ""
                memories = self._mem_retriever.search(
                    event.workspace_id, query
                )
            except Exception:
                memories = self._mem_retriever.list_recent(event.workspace_id)
        text_projection = str(event.payload.get("text", "") or "")
        ctx_items = self._ctx_engine.build(
            recent_messages=recent_messages,
            memories=memories,
            current_message=text_projection,
            db=self._db,
            trace_id="",
            workspace_id=event.workspace_id,
            session_summary=self._compression.get_latest(
                event.workspace_id, event.session_id
            ),
        )
        # Store extra content for multimodal routing
        raw = event.payload.get("content", [])
        self._extra_content = raw if isinstance(raw, list) else []
        return ctx_items

    def _update_session_summary(self, event: RuntimeEvent) -> None:
        try:
            self._compression.update_summary(event.workspace_id, event.session_id)
        except Exception:
            # Compression is a derived optimization and must not fail a turn.
            return

    def _build_model_messages(
        self, event: RuntimeEvent, message: str, trace: object,
        ctx: list[ContextItem] | None = None,
    ) -> list[dict[str, object]]:
        if ctx is None:
            ctx = self._build_context(event)
        extra_content = self._get_extra_content(event)
        span = getattr(trace, "_current_span", None) or trace

        # Resolve attachment references to data URIs for native vision models
        resolved_content = self._resolve_attachment_content(extra_content, event.workspace_id)

        # Collect vision observations context for attachments
        vision_context = self._build_vision_context(
            resolved_content, event.workspace_id, event.session_id,
        )

        should_delegate_vision = (
            has_image(resolved_content) and not self._supports_vision()
        )
        if should_delegate_vision:
            text_only_content, text_only_message = self._run_vision_pipeline(
                resolved_content, message, trace, span, event=event,
            )
            return self._prompt_builder.build(
                ctx_items=ctx,
                current_message=text_only_message,
                tool_results=self._tool_results,
                extra_content=text_only_content,
                vision_context=vision_context,
            )

        has_pending_attachments = any(
            getattr(p, "attachment_id", None) and getattr(p, "get_uri_or_attachment", lambda: "")()
            for p in (resolved_content or [])
        ) if resolved_content else False

        return self._prompt_builder.build(
            ctx_items=ctx,
            current_message=message,
            tool_results=self._tool_results,
            extra_content=resolved_content if has_image(resolved_content) else resolved_content,
            vision_context=vision_context,
        )

    def _resolve_attachment_content(
        self, extra_content: list[ContentPart], workspace_id: str,
    ) -> list[ContentPart]:
        """Resolve ImagePart.attachment_id to data URIs for native vision models."""
        resolved: list[ContentPart] = []
        for part in extra_content:
            if isinstance(part, ImagePart) and part.attachment_id and not part.uri:
                if self._vision_service:
                    try:
                        att = self._vision_service.require_attachment(
                            part.attachment_id, workspace_id,
                        )
                        raw = self._vision_service.read_attachment_bytes(att)
                        from cogito_agent.media import MediaProcessor
                        proc = MediaProcessor()
                        prepared = proc.validate_and_prepare(raw, filename=att.original_filename)
                        data_uri = proc.to_data_uri(prepared)
                        resolved.append(ImagePart(
                            uri=data_uri,
                            mime_type=prepared.mime_type,
                            width=prepared.width,
                            height=prepared.height,
                            attachment_id=part.attachment_id,
                        ))
                    except Exception:
                        resolved.append(TextPart(
                            text=f"[Attachment {part.attachment_id}: failed to load]"
                        ))
                else:
                    resolved.append(TextPart(
                        text=f"[Attachment {part.attachment_id}]"
                    ))
            else:
                resolved.append(part)
        return resolved

    def _build_vision_context(
        self, extra_content: list[ContentPart],
        workspace_id: str, session_id: str,
    ) -> str:
        """Build vision observation context string for prompt injection."""
        if not self._vision_service:
            return ""
        attachment_ids: list[str] = []
        for part in (extra_content or []):
            if isinstance(part, ImagePart) and part.attachment_id:
                attachment_ids.append(part.attachment_id)
            elif isinstance(part, ImagePart) and part.uri:
                pass
        if not attachment_ids:
            return ""
        try:
            return self._vision_service.format_observations_for_context(
                attachment_ids, workspace_id,
            )
        except Exception:
            return ""

    def _supports_vision(self) -> bool:
        """Check if the primary model adapter supports vision natively."""
        adapter = self._model_adapter
        if adapter is None:
            return False
        router = getattr(adapter, "_router", None)
        if router is None:
            return False
        candidates = getattr(router, "_candidates", {})
        return any(
            "image" in c.input_modalities or "vision" in c.capabilities
            for c in candidates.values()
        )

    def _get_extra_content(self, event: RuntimeEvent) -> list[ContentPart]:
        raw = event.payload.get("content", [])
        if isinstance(raw, list):
            return normalize_content(raw)
        return []

    def _generate_reply(
        self, event: RuntimeEvent, message: str,
        trace: object, span: object,
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

    def _bind_route_observer(
        self, event: RuntimeEvent, trace: object, parent_span: object
    ) -> None:
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
                "fallback_order": [
                    item.id for item in route_event.decision.fallback_order
                ],
                "exclusions": [
                    exclusion.model_dump()
                    for exclusion in route_event.decision.exclusions
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
                decision = (
                    "fallback" if route_event.remaining_candidates else "fail"
                )
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
        self, event: RuntimeEvent, resp: ModelResponse,
        trace: object, span: object,
    ) -> ModelResponse:
        collected_results: list[dict[str, object]] = []
        for intent in resp.tool_intents:
            capability_name = intent.capability_name
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
                    event, capability_name, intent, policy_req, policy_dec
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
            args = dict(intent.arguments) if intent.arguments else {}
            tool_start = datetime.now(UTC)

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

            dec_value = (
                policy_dec.decision.value
                if hasattr(policy_dec.decision, "value")
                else str(policy_dec.decision)
            )
            tool_redactions = (
                list(getattr(tool_result, "redactions", [])) if tool_result else []
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
                redactions=tool_redactions or None,
            )

            self._audit.log(
                actor_id=event.actor_id, action="call_tool",
                resource=capability_name,
                workspace_id=event.workspace_id,
                session_id=event.session_id,
                trace_id=str(getattr(trace, "id", "")),
                decision="allow", reason=policy_dec.reason,
            )

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
                event_with_text, "", trace,
            )
            follow_up_msgs.append({
                "role": "assistant",
                "content": str(resp.content),
            })
            for r in collected_results:
                raw = str(r.get("summary", "") or r.get("error", ""))
                tool_call_id = intent.tool_call_id if hasattr(intent, 'tool_call_id') else ""
                follow_up_msgs.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": wrap_untrusted(raw),
                })
            tool_schemas = self._get_tool_schemas(actor=event.actor_id)
            kwargs: dict[str, object] = {}
            if tool_schemas:
                kwargs["tools"] = tool_schemas
            follow_up = self._model_adapter.chat(follow_up_msgs, **kwargs)
            self._model_call_count += 1
            return follow_up

        return resp

    def _create_approval(
        self, event: RuntimeEvent, capability_name: str,
        intent: ToolIntent, policy_req: PolicyRequest, policy_dec: object,
    ) -> str:
        repo = ApprovalRepository(self._db)
        reason = (
            str(policy_dec.reason)
            if hasattr(policy_dec, "reason")
            else "require_approval"
        )
        tool_call_json = json.dumps({
            "capability_name": capability_name,
            "arguments": intent.arguments,
            "tool_call_id": intent.tool_call_id,
        })
        record = repo.create(
            workspace_id=event.workspace_id,
            actor_id=event.actor_id,
            capability_name=capability_name,
            operation=str(policy_req.operation),
            resource=str(policy_req.resource),
            reason=reason,
            session_id=event.session_id,
            tool_call_json=tool_call_json,
        )
        return str(record.get("id", ""))

    def _compose_result(
        self, event: RuntimeEvent, resp: ModelResponse,
        trace: object, span: object,
    ) -> ComposedResult:
        return self._result_composer.compose(
            resp,
            sources=self._sources,
            tool_summaries=self._tool_results,
        )

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

    def _persist_user_message(self, event: RuntimeEvent) -> None:
        raw = event.payload.get("text", "")
        user_text = str(raw) if raw is not None else ""
        content_raw = event.payload.get("content", [])
        has_multimodal = bool(content_raw) and (
            not user_text.strip() or any(
                isinstance(c, dict) and c.get("type") in ("image", "file")
                for c in (content_raw if isinstance(content_raw, list) else [])
            )
        )
        persist_text = user_text or "[multimodal message]" if has_multimodal else (user_text or "")
        if persist_text.strip():
            mid = str(uuid.uuid4())
            meta = {}
            if has_multimodal:
                meta["content_types"] = list({
                    (c.get("type", "text") if isinstance(c, dict) else "text")
                    for c in (content_raw if isinstance(content_raw, list) else [])
                })
            self._msg_repo.create(
                mid, event.workspace_id, event.session_id, "user", persist_text,
            )
            title = user_text[:80] if user_text.strip() else "[multimodal]"
            self._db.connection.execute(
                "UPDATE sessions SET title = CASE"
                " WHEN title IS NULL OR title = '' THEN ? ELSE title END,"
                " updated_at = datetime('now')"
                " WHERE id = ? AND workspace_id = ?",
                (title, event.session_id, event.workspace_id),
            )
            self._db.connection.commit()

    def _persist(self, event: RuntimeEvent, output: str, trace_id: str = "") -> None:
        mid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO messages"
            " (id, workspace_id, session_id, role, content, metadata_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                mid,
                event.workspace_id,
                event.session_id,
                "assistant",
                output,
                json.dumps({"trace_id": trace_id}) if trace_id else "{}",
            ),
        )
        self._db.connection.execute(
            "UPDATE sessions SET updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ?",
            (event.session_id, event.workspace_id),
        )
        self._db.connection.commit()
