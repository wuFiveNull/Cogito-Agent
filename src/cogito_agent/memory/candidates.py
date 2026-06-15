from __future__ import annotations

import re
import uuid

from cogito_agent.storage import Database

_PREFERENCE_PATTERNS = [
    re.compile(r"\b(?:I |we )?(?:like|love|prefer|enjoy|favorite)\s", re.I),
    re.compile(r"\b(?:I |we )?(?:don'?t like|hate|dislike|avoid)\s", re.I),
    re.compile(r"\b(?:I |we )?(?:want|wish|hope|need)\s", re.I),
]

_FACT_PATTERNS = [
    re.compile(r"\b(?:my name is|I am|I'm|we are)\s", re.I),
    re.compile(r"\b(?:I |we )?(?:work at|study at|live in|from)\s", re.I),
    re.compile(r"\b(?:the |our )?(?:project|task|goal|deadline) is\b", re.I),
]

_DECISION_PATTERNS = [
    re.compile(r"\b(?:I |we )?(?:decided|chose|selected|picked)\s", re.I),
    re.compile(r"\blet'?s (?:use|go with|try)\b", re.I),
]


class CandidateExtractor:
    def __init__(self, db: Database) -> None:
        self._db = db

    def extract(
        self,
        workspace_id: str,
        session_id: str,
        source_message_id: str,
        text: str,
        type: str = "general",
        reason: str = "",
        confidence: float = 0.5,
    ) -> dict[str, object]:
        cid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_candidates"
            " (id, workspace_id, session_id, text, type, reason, confidence,"
            " source_message_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, workspace_id, session_id, text, type, reason, confidence,
             source_message_id),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        row = cur.fetchone()
        return dict(row) if row else {"id": cid}

    def extract_from_turn(
        self,
        workspace_id: str,
        session_id: str,
        source_message_id: str,
        text: str,
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        for sent in sentences:
            if not sent or len(sent) < 10:
                continue
            ctype, confidence = self._classify(sent)
            if ctype != "general" or confidence > 0.3:
                result = self.extract(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    source_message_id=source_message_id,
                    text=sent.strip(),
                    type=ctype,
                    reason=f"auto_extracted_{ctype}",
                    confidence=confidence,
                )
                results.append(result)
        if not results and len(text.strip()) > 20:
            result = self.extract(
                workspace_id=workspace_id,
                session_id=session_id,
                source_message_id=source_message_id,
                text=text.strip(),
                type="general",
                reason="auto_extracted_general",
                confidence=0.3,
            )
            results.append(result)
        return results

    def _classify(self, sentence: str) -> tuple[str, float]:
        for pattern in _PREFERENCE_PATTERNS:
            if pattern.search(sentence):
                return ("preference", 0.7)
        for pattern in _FACT_PATTERNS:
            if pattern.search(sentence):
                return ("profile", 0.8)
        for pattern in _DECISION_PATTERNS:
            if pattern.search(sentence):
                return ("task", 0.6)
        return ("general", 0.3)
