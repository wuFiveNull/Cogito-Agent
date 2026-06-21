from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.models import OpenAICompatibleAdapter
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database


def _mock_openai_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__.return_value = mock
    return mock


@patch("cogito_agent.models.openai_adapter.urllib.request.urlopen")
def test_e2e_full_turn(mock_urlopen: MagicMock) -> None:
    mock_urlopen.return_value = _mock_openai_response(
        {
            "id": "chatcmpl-demo",
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "message": {"content": "Hello! I'm Cogito-Agent, your local AI assistant."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 12},
        }
    )

    db = Database(":memory:")
    db.initialize()

    ws_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "demo"))
    db.connection.execute(
        "INSERT INTO sessions (id, workspace_id, title, status) VALUES (?, ?, ?, ?)",
        (sess_id, ws_id, "E2E Test", "active"),
    )
    db.connection.commit()

    adapter = OpenAICompatibleAdapter(api_key="test-key", model="gpt-4o-mini")
    kernel = RuntimeKernel(db, model_adapter=adapter)

    event = RuntimeEvent(
        workspace_id=ws_id,
        session_id=sess_id,
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "Hello!"},
    )

    result = kernel.process(event)
    assert result.state.value == "completed"
    assert result.error is None
    assert "Cogito-Agent" in result.output

    cur = db.connection.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
        (sess_id,),
    )
    msgs = cur.fetchall()
    assert len(msgs) >= 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"

    cur_t = db.connection.execute("SELECT id, status FROM traces WHERE workspace_id = ?", (ws_id,))
    traces = cur_t.fetchall()
    assert len(traces) >= 1


@patch("cogito_agent.models.openai_adapter.urllib.request.urlopen")
def test_e2e_model_error(mock_urlopen: MagicMock) -> None:
    import urllib.error

    err_resp = MagicMock()
    err_resp.read.return_value = b'{"error": "rate limit"}'
    err_resp.__enter__.return_value = err_resp
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "http://example.com", 429, "Rate Limited", {}, err_resp
    )

    db = Database(":memory:")
    db.initialize()
    ws_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "demo"))
    db.connection.execute(
        "INSERT INTO sessions (id, workspace_id, title, status) VALUES (?, ?, ?, ?)",
        (sess_id, ws_id, "E2E Error Test", "active"),
    )
    db.connection.commit()

    adapter = OpenAICompatibleAdapter(api_key="bad-key")
    kernel = RuntimeKernel(db, model_adapter=adapter)

    event = RuntimeEvent(
        workspace_id=ws_id,
        session_id=sess_id,
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "Hi"},
    )

    result = kernel.process(event)
    assert result.error or "error" in result.output.lower()


def test_e2e_no_model_echo() -> None:
    db = Database(":memory:")
    db.initialize()
    ws_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "demo"))
    db.connection.execute(
        "INSERT INTO sessions (id, workspace_id, title, status) VALUES (?, ?, ?, ?)",
        (sess_id, ws_id, "E2E Echo Test", "active"),
    )
    db.connection.commit()

    kernel = RuntimeKernel(db)

    event = RuntimeEvent(
        workspace_id=ws_id,
        session_id=sess_id,
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "hello world"},
    )

    result = kernel.process(event)
    assert result.state.value == "completed"
    assert "You said: hello world" in result.output
