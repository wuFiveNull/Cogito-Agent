from cogito_agent.memory import CandidateExtractor
from cogito_agent.storage import Database


def test_extract_candidate(db: Database) -> None:
    extractor = CandidateExtractor(db)
    result = extractor.extract(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text="User prefers concise answers",
        type="preference",
        reason="Extracted from conversation",
        confidence=0.8,
    )
    assert result["text"] == "User prefers concise answers"
    assert result["type"] == "preference"
    assert result["status"] == "pending"
