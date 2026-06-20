from __future__ import annotations

from cogito_agent.models import ModelResponse
from cogito_agent.runtime import ResultComposer


def test_result_composer_builds_stable_structured_result() -> None:
    result = ResultComposer().compose(
        ModelResponse(content="Answer"),
        sources=[
            {
                "source_type": "memory",
                "source_id": "m1",
                "label": "Preference",
                "text": "User prefers concise answers",
                "source_lineage": {"memory_id": "m1", "version": 2},
            },
            {"source_type": "memory", "source_id": "m1", "text": "duplicate"},
        ],
        tool_summaries=[
            {"tool": "time.now", "status": "completed", "summary": "12:00"}
        ],
        artifacts=[
            {"id": "a1", "title": "Report", "artifact_type": "markdown"}
        ],
        suggestions=[{"label": "Open report", "action": "artifact:a1"}],
    )

    assert result.render_text() == "Answer"
    assert len(result.citations) == 1
    assert result.citations[0].id == "cite-1"
    assert result.citations[0].lineage["version"] == 2
    assert result.tool_summaries[0].capability_name == "time.now"
    assert result.artifacts[0].id == "a1"
    assert result.suggestions[0].action == "artifact:a1"


def test_result_composer_normalizes_model_error() -> None:
    result = ResultComposer().compose(ModelResponse(error="provider unavailable"))
    assert result.answer == "Model error: provider unavailable"
