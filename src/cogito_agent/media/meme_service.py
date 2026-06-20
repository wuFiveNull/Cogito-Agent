from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.media.processor import (
    MediaProcessor,
)
from cogito_agent.media.types import Attachment, MemeAsset, create_meme_id
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    AttachmentRepository,
    MemeAssetRepository,
    VisionObservationRepository,
)

logger = logging.getLogger(__name__)

ANALYZE_MEME_SYSTEM_PROMPT = (
    "Analyze this image as a chat meme/sticker for use in conversations.\n\n"
    "Output ONLY valid JSON matching this schema. NO markdown fences, NO extra text:\n"
    '{"name": "short name", "aliases": ["alias1"], "description": "brief visual and meaning",'
    ' "emotions": ["emotion1"], "use_cases": ["when to send"],'
    ' "avoid_cases": ["when not to send"], "text_on_image": "visible text or null"}'
)


class MemeNotFoundError(ValueError):
    pass


class MemeDisabledError(ValueError):
    pass


class MemeAnalysisError(RuntimeError):
    pass


class MemeService:
    def __init__(
        self,
        db: Database,
        media_processor: MediaProcessor | None = None,
    ) -> None:
        self._db = db
        self._meme_repo = MemeAssetRepository(db)
        self._att_repo = AttachmentRepository(db)
        self._obs_repo = VisionObservationRepository(db)
        self._processor = media_processor or MediaProcessor()
        self._vision_service: Any = None
        self._tracer: Any = None
        self._audit: Any = None
        self._current_workspace_id: str = ""
        self._current_trace_id: str = ""

    def set_vision_service(self, svc: Any) -> None:
        self._vision_service = svc

    def set_tracer(self, tracer: Any) -> None:
        self._tracer = tracer

    def set_audit(self, audit: Any) -> None:
        self._audit = audit

    def set_current_context(self, workspace_id: str = "", trace_id: str = "") -> None:
        self._current_workspace_id = workspace_id
        self._current_trace_id = trace_id

    # ── Trace/audit helpers ──────────────────────────────────────────

    def _log_span(self, trace_id: str, name: str, inp: str = "", out: str = "") -> None:
        if self._tracer is None or not trace_id:
            return
        span = self._tracer.create_span(trace_id, name, None)
        if span:
            span.input_summary = inp[:200]
            span.output_summary = out[:200]
            self._tracer.end_span(span)

    def _log_audit(
        self, actor: str, action: str, meme_id: str, ws: str, details: str = "",
        redact: bool = True,
    ) -> None:
        if self._audit is None:
            return
        self._audit.log(
            actor_id=actor, action=action, resource=f"meme:{meme_id}",
            workspace_id=ws, details=details, redact_details=redact,
        )

    # ── Internal helpers ─────────────────────────────────────────────

    def _get_attachment(self, attachment_id: str, workspace_id: str) -> Attachment:
        record = self._att_repo.get_by_id(attachment_id, workspace_id)
        if record is None:
            raise MemeNotFoundError(f"Attachment {attachment_id} not found in workspace")
        return Attachment(
            id=str(record["id"]),
            workspace_id=str(record["workspace_id"]),
            session_id=str(record.get("session_id")) if record.get("session_id") else None,
            content_hash=str(record["content_hash"]),
            media_type=str(record["media_type"]),
            original_filename=str(record["original_filename"]),
            storage_path=str(record["storage_path"]),
            size_bytes=int(str(record.get("size_bytes", 0))),
            width=int(str(record.get("width", 0))) if record.get("width") else None,
            height=int(str(record.get("height", 0))) if record.get("height") else None,
            created_at=datetime.fromisoformat(str(record["created_at"])),
        )

    def _to_meme_asset(self, record: dict[str, object]) -> MemeAsset:
        import unicodedata
        def _parse_json_list(val: object) -> list[str]:
            if isinstance(val, list):
                return [str(v) for v in val]
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return [str(v) for v in parsed]
                    return []
                except (json.JSONDecodeError, TypeError):
                    pass
            return []
        name = unicodedata.normalize("NFKC", str(record.get("name", "")))
        return MemeAsset(
            id=str(record["id"]),
            workspace_id=str(record["workspace_id"]),
            attachment_id=str(record["attachment_id"]),
            content_hash=str(record["content_hash"]),
            name=name,
            aliases=[unicodedata.normalize("NFKC", str(a)) for a in _parse_json_list(record.get("aliases_json"))],
            description=str(record.get("description", "")),
            emotions=_parse_json_list(record.get("emotions_json")),
            use_cases=_parse_json_list(record.get("use_cases_json")),
            avoid_cases=_parse_json_list(record.get("avoid_cases_json")),
            text_on_image=str(record["text_on_image"]) if record.get("text_on_image") else None,
            source=str(record.get("source", "manual")),
            enabled=bool(record.get("enabled", 1)),
            use_count=int(str(record.get("use_count", 0))),
            last_used_at=datetime.fromisoformat(str(record["last_used_at"])) if record.get("last_used_at") else None,
            created_at=datetime.fromisoformat(str(record["created_at"])),
            updated_at=datetime.fromisoformat(str(record["updated_at"])),
        )

    # ── register_meme ───────────────────────────────────────────────

    def register_meme(
        self,
        attachment_id: str,
        name: str,
        description: str,
        workspace_id: str,
        aliases: list[str] | None = None,
        emotions: list[str] | None = None,
        use_cases: list[str] | None = None,
        avoid_cases: list[str] | None = None,
        text_on_image: str | None = None,
        trace_id: str = "",
        actor_id: str = "system",
    ) -> MemeAsset:
        attachment = self._get_attachment(attachment_id, workspace_id)

        existing = self._meme_repo.get_by_attachment_id(attachment_id, workspace_id)
        if existing:
            meme = self._to_meme_asset(existing)
            self._log_span(trace_id, "meme.register", f"attachment={attachment_id}", "already_exists")
            return meme

        content_hash = attachment.content_hash
        same_hash = self._meme_repo.find_by_content_hash(content_hash, workspace_id)
        if same_hash:
            meme = self._to_meme_asset(same_hash[0])
            self._log_span(trace_id, "meme.register", f"attachment={attachment_id}", "reused_by_hash")
            return meme

        meme_id = create_meme_id()
        record = self._meme_repo.create(
            meme_id=meme_id,
            workspace_id=workspace_id,
            attachment_id=attachment_id,
            content_hash=content_hash,
            name=name,
            description=description,
            source="manual",
            aliases=aliases,
            emotions=emotions,
            use_cases=use_cases,
            avoid_cases=avoid_cases,
            text_on_image=text_on_image,
        )
        self._log_span(trace_id, "meme.register", f"attachment={attachment_id}", f"meme_id={meme_id}")
        self._log_audit(actor_id, "meme.register", meme_id, workspace_id,
                        json.dumps({"source": "manual", "name": name}))
        return self._to_meme_asset(record)

    # ── analyze_meme ────────────────────────────────────────────────

    def analyze_meme(
        self,
        attachment_id: str,
        workspace_id: str,
        force_refresh: bool = False,
        trace_id: str = "",
        actor_id: str = "system",
    ) -> MemeAsset:
        if self._vision_service is None:
            raise MemeAnalysisError("No vision service configured for meme analysis")

        attachment = self._get_attachment(attachment_id, workspace_id)

        existing = self._meme_repo.get_by_attachment_id(attachment_id, workspace_id)
        if existing and not force_refresh:
            self._log_span(trace_id, "meme.analyze", f"attachment={attachment_id}", "already_exists")
            return self._to_meme_asset(existing)

        content_hash = attachment.content_hash
        if not force_refresh:
            same_hash = self._meme_repo.find_by_content_hash(content_hash, workspace_id)
            if same_hash:
                self._log_span(trace_id, "meme.analyze", f"attachment={attachment_id}", "reused_by_hash")
                return self._to_meme_asset(same_hash[0])

        result_text = self._vision_service.inspect_image(
            attachment_id=attachment_id,
            prompt=ANALYZE_MEME_SYSTEM_PROMPT,
            workspace_id=workspace_id,
            trace_id=trace_id,
        )

        parsed = self._parse_analysis_json(result_text)
        name = parsed.get("name", "Unnamed meme")
        description = parsed.get("description", "")
        aliases = parsed.get("aliases", [])
        emotions = parsed.get("emotions", [])
        use_cases = parsed.get("use_cases", [])
        avoid_cases = parsed.get("avoid_cases", [])
        text_on_image = parsed.get("text_on_image")

        if not name or not description:
            raise MemeAnalysisError(
                "VLM returned incomplete meme profile. "
                f"Missing name or description. Raw: {result_text[:200]}"
            )

        meme_id = create_meme_id()
        record = self._meme_repo.create(
            meme_id=meme_id,
            workspace_id=workspace_id,
            attachment_id=attachment_id,
            content_hash=content_hash,
            name=name,
            description=description,
            source="vision",
            aliases=aliases,
            emotions=emotions,
            use_cases=use_cases,
            avoid_cases=avoid_cases,
            text_on_image=text_on_image,
        )
        self._log_span(trace_id, "meme.analyze", f"attachment={attachment_id}", f"meme_id={meme_id}")
        self._log_audit(actor_id, "meme.analyze", meme_id, workspace_id,
                        json.dumps({"source": "vision", "name": name}))
        return self._to_meme_asset(record)

    def _parse_analysis_json(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
        for _ in range(3):
            for prefix in ("{", "["):
                idx = cleaned.find(prefix)
                if idx >= 0:
                    try:
                        result = json.loads(cleaned[idx:])
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        pass
            break
        open_count = cleaned.count("{")
        close_count = cleaned.count("}")
        if open_count > close_count:
            cleaned += "}" * (open_count - close_count)
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        raise MemeAnalysisError(
            f"VLM output is not valid JSON. Raw: {text[:300]}"
        )

    # ── search_memes ────────────────────────────────────────────────

    def search_memes(
        self, query: str, workspace_id: str, limit: int = 5,
        trace_id: str = "", actor_id: str = "system",
    ) -> list[dict[str, object]]:
        results = self._meme_repo.search(workspace_id, query, limit)
        safe = []
        for r in results:
            safe.append({
                "meme_id": r["id"],
                "name": r.get("name", ""),
                "description": r.get("description", ""),
                "emotions": r.get("emotions_json", []),
                "use_cases": r.get("use_cases_json", []),
            })
        self._log_span(trace_id, "meme.search", f"query={query}", f"count={len(safe)}")
        return safe

    # ── send_meme ───────────────────────────────────────────────────

    def send_meme(
        self,
        meme_id: str,
        workspace_id: str,
        caption: str = "",
        trace_id: str = "",
        actor_id: str = "system",
    ) -> dict[str, object]:
        record = self._meme_repo.get(meme_id, workspace_id)
        if record is None:
            raise MemeNotFoundError(f"Meme {meme_id} not found in workspace")
        if not record.get("enabled"):
            raise MemeDisabledError(f"Meme {meme_id} is disabled")

        attachment = self._get_attachment(str(record["attachment_id"]), workspace_id)

        self._meme_repo.record_use(meme_id, workspace_id)

        result: dict[str, object] = {
            "meme_id": meme_id,
            "name": record.get("name", ""),
            "attachment_id": attachment.id,
            "media_type": attachment.media_type,
            "image_bytes": None,
            "caption": caption or "",
            "vision_model_called": False,
        }

        self._log_span(trace_id, "meme.send",
                       f"meme_id={meme_id} caption={caption[:50]}",
                       "vision_model_called=false")
        self._log_audit(actor_id, "meme.send", meme_id, workspace_id,
                        json.dumps({"caption": caption[:100], "vision_model_called": False}))
        return result

    # ── Capability registration ─────────────────────────────────────

    def register_with_capability_registry(
        self, cap_reg: CapabilityRegistry,
    ) -> None:
        from cogito_agent.capability.tools import (
            ANALYZE_MEME_MANIFEST,
            REGISTER_MEME_MANIFEST,
            SEARCH_MEMES_MANIFEST,
            SEND_MEME_MANIFEST,
        )

        def _register_meme_fn(
            attachment_id: str, name: str, description: str,
            aliases: list[str] | None = None,
            emotions: list[str] | None = None,
            use_cases: list[str] | None = None,
            avoid_cases: list[str] | None = None,
            text_on_image: str | None = None,
            **_kwargs: object,
        ) -> ToolResult:
            try:
                ws = str(_kwargs.get("workspace_id") or self._current_workspace_id or "")
                trace = str(_kwargs.get("trace_id") or self._current_trace_id or "")
                actor = str(_kwargs.get("actor_id") or "system")
                meme = self.register_meme(
                    attachment_id=attachment_id, name=name, description=description,
                    workspace_id=ws, aliases=aliases, emotions=emotions,
                    use_cases=use_cases, avoid_cases=avoid_cases,
                    text_on_image=text_on_image, trace_id=trace, actor_id=actor,
                )
                return ToolResult(status="ok", summary=f"Registered meme '{meme.name}' (id={meme.id})")
            except (MemeNotFoundError, ValueError) as e:
                return ToolResult(status="error", summary=str(e))

        def _analyze_meme_fn(
            attachment_id: str, force_refresh: bool = False, **_kwargs: object,
        ) -> ToolResult:
            try:
                ws = str(_kwargs.get("workspace_id") or self._current_workspace_id or "")
                trace = str(_kwargs.get("trace_id") or self._current_trace_id or "")
                actor = str(_kwargs.get("actor_id") or "system")
                meme = self.analyze_meme(
                    attachment_id=attachment_id, workspace_id=ws,
                    force_refresh=force_refresh, trace_id=trace, actor_id=actor,
                )
                return ToolResult(status="ok", summary=f"Analyzed meme '{meme.name}' (id={meme.id}, source={meme.source})")
            except (MemeNotFoundError, MemeAnalysisError, ValueError) as e:
                return ToolResult(status="error", summary=str(e))

        def _search_memes_fn(
            query: str, limit: int = 5, **_kwargs: object,
        ) -> ToolResult:
            try:
                ws = str(_kwargs.get("workspace_id") or self._current_workspace_id or "")
                trace = str(_kwargs.get("trace_id") or self._current_trace_id or "")
                actor = str(_kwargs.get("actor_id") or "system")
                results = self.search_memes(query, ws, limit, trace_id=trace, actor_id=actor)
                if not results:
                    return ToolResult(status="ok", summary="No memes found matching query")
                lines = []
                for r in results:
                    name = str(r.get("name", ""))
                    mid = str(r.get("meme_id", ""))
                    desc = str(r.get("description", ""))[:60]
                    lines.append(f"{name} (id={mid}): {desc}")
                return ToolResult(status="ok", summary="\n".join(lines))
            except Exception as e:
                return ToolResult(status="error", summary=str(e))

        def _send_meme_fn(meme_id: str, caption: str = "", **_kwargs: object) -> ToolResult:
            try:
                ws = str(_kwargs.get("workspace_id") or self._current_workspace_id or "")
                trace = str(_kwargs.get("trace_id") or self._current_trace_id or "")
                actor = str(_kwargs.get("actor_id") or "system")
                result = self.send_meme(meme_id, ws, caption, trace_id=trace, actor_id=actor)
                return ToolResult(
                    status="ok",
                    summary=f"Sent meme '{result.get('name', '')}' (id={meme_id})",
                    data=result,
                )
            except (MemeNotFoundError, MemeDisabledError, ValueError) as e:
                return ToolResult(status="error", summary=str(e))

        cap_reg.register("register_meme", REGISTER_MEME_MANIFEST, _register_meme_fn)
        cap_reg.register("analyze_meme", ANALYZE_MEME_MANIFEST, _analyze_meme_fn)
        cap_reg.register("search_memes", SEARCH_MEMES_MANIFEST, _search_memes_fn)
        cap_reg.register("send_meme", SEND_MEME_MANIFEST, _send_meme_fn)
