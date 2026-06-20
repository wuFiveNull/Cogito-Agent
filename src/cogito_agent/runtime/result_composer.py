from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cogito_agent.models import ModelResponse


class Citation(BaseModel):
    id: str
    source_type: str = ""
    source_id: str = ""
    label: str = ""
    excerpt: str = ""
    lineage: dict[str, Any] = Field(default_factory=dict)


class ComposedToolSummary(BaseModel):
    capability_name: str
    status: str = ""
    summary: str = ""
    error: str = ""


class ArtifactReference(BaseModel):
    id: str
    title: str = ""
    artifact_type: str = ""
    url: str = ""


class ResultSuggestion(BaseModel):
    label: str
    action: str = ""
    reason: str = ""


class ComposedResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    tool_summaries: list[ComposedToolSummary] = Field(default_factory=list)
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    suggestions: list[ResultSuggestion] = Field(default_factory=list)

    def render_text(self) -> str:
        return self.answer


class ResultComposer:
    """Compose provider-neutral runtime output into one stable result contract."""

    def compose(
        self,
        response: ModelResponse,
        *,
        sources: list[dict[str, object]] | None = None,
        tool_summaries: list[dict[str, object]] | None = None,
        artifacts: list[dict[str, object]] | None = None,
        suggestions: list[dict[str, object]] | None = None,
    ) -> ComposedResult:
        answer = f"Model error: {response.error}" if response.error else response.content
        return ComposedResult(
            answer=answer,
            citations=self._citations(sources or []),
            tool_summaries=self._tools(tool_summaries or []),
            artifacts=[ArtifactReference.model_validate(item) for item in artifacts or []],
            suggestions=[ResultSuggestion.model_validate(item) for item in suggestions or []],
        )

    @staticmethod
    def _citations(sources: list[dict[str, object]]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[tuple[str, str]] = set()
        for source in sources:
            source_type = str(source.get("source_type", source.get("type", "")))
            source_id = str(source.get("source_id", source.get("id", "")))
            key = (source_type, source_id)
            if key in seen:
                continue
            seen.add(key)
            lineage_raw = source.get("source_lineage", source.get("lineage", {}))
            lineage = lineage_raw if isinstance(lineage_raw, dict) else {}
            citations.append(
                Citation(
                    id=f"cite-{len(citations) + 1}",
                    source_type=source_type,
                    source_id=source_id,
                    label=str(source.get("label", source.get("title", ""))),
                    excerpt=str(source.get("excerpt", source.get("text", "")))[:500],
                    lineage={str(key): value for key, value in lineage.items()},
                )
            )
        return citations

    @staticmethod
    def _tools(items: list[dict[str, object]]) -> list[ComposedToolSummary]:
        results: list[ComposedToolSummary] = []
        for item in items:
            results.append(
                ComposedToolSummary(
                    capability_name=str(
                        item.get("capability_name", item.get("tool", ""))
                    ),
                    status=str(item.get("status", "")),
                    summary=str(item.get("summary", item.get("output", "")))[:1000],
                    error=str(item.get("error", ""))[:1000],
                )
            )
        return results
