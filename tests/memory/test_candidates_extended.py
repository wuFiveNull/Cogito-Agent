from cogito_agent.memory import CandidateExtractor
from cogito_agent.storage import Database


def test_extract_from_turn_preference(db: Database) -> None:
    extractor = CandidateExtractor(db)
    results = extractor.extract_from_turn(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text="I really like using Python for data analysis.",
    )
    assert len(results) >= 1
    assert any(r["type"] == "preference" for r in results)


def test_extract_from_turn_profile(db: Database) -> None:
    extractor = CandidateExtractor(db)
    results = extractor.extract_from_turn(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text="My name is Alice and I work at Acme Corp.",
    )
    assert len(results) >= 1
    assert any(r["type"] == "profile" for r in results)


def test_extract_from_turn_task(db: Database) -> None:
    extractor = CandidateExtractor(db)
    results = extractor.extract_from_turn(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text="I decided to use FastAPI for the backend.",
    )
    assert len(results) >= 1
    assert any(r["type"] == "task" for r in results)


def test_extract_from_turn_fallback_general(db: Database) -> None:
    extractor = CandidateExtractor(db)
    results = extractor.extract_from_turn(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text="This is a general statement about the weather today.",
    )
    assert len(results) >= 1
    assert any(r["type"] == "general" for r in results)


def test_extract_from_turn_short_text_skipped(db: Database) -> None:
    extractor = CandidateExtractor(db)
    results = extractor.extract_from_turn(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text="Hi",
    )
    assert len(results) == 0


def test_extract_from_turn_multiple_sentences(db: Database) -> None:
    extractor = CandidateExtractor(db)
    results = extractor.extract_from_turn(
        workspace_id="ws-1",
        session_id="sess-1",
        source_message_id="msg-1",
        text=(
            "My name is Bob. I prefer dark mode. "
            "I decided to use SQLite for storage."
        ),
    )
    assert len(results) >= 2
