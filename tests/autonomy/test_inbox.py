from __future__ import annotations

import uuid


def test_write_inbox_creates_item(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "Test Title", "Test Body")
    assert iid is not None
    assert isinstance(iid, str)

    items = gate.list_inbox(wid)
    ids = [i["id"] for i in items]
    assert iid in ids


def test_list_inbox_returns_items(gate, wid: str) -> None:
    gate.write_inbox(wid, "Title A", "Body A")
    gate.write_inbox(wid, "Title B", "Body B")
    items = gate.list_inbox(wid)
    assert len(items) >= 2


def test_list_inbox_wildcard(gate, wid: str) -> None:
    gate.write_inbox(wid, "Wildcard", "Test")
    items = gate.list_inbox("*")
    assert len(items) >= 1


def test_list_inbox_limit(gate, wid: str) -> None:
    for i in range(5):
        gate.write_inbox(wid, f"Title {i}", f"Body {i}")
    items = gate.list_inbox(wid, limit=3)
    assert len(items) <= 3


def test_read_inbox_item_returns_item(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "Readable", "Read Body")
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["title"] == "Readable"
    assert item["body"] == "Read Body"


def test_read_inbox_item_marks_read(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "Mark Read", "Body")
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["read_at"] is None

    gate.mark_inbox_read(iid)
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["read_at"] is not None


def test_mark_inbox_read_specific_item(gate, wid: str) -> None:
    iid1 = gate.write_inbox(wid, "First", "Body1")
    iid2 = gate.write_inbox(wid, "Second", "Body2")

    gate.mark_inbox_read(iid1)

    item1 = gate.read_inbox_item(iid1)
    assert item1 is not None
    assert item1["read_at"] is not None

    item2 = gate.read_inbox_item(iid2)
    assert item2 is not None
    assert item2["read_at"] is None


def test_read_inbox_nonexistent_returns_none(gate, wid: str) -> None:
    item = gate.read_inbox_item("nonexistent-id")
    assert item is None


def test_clear_inbox_removes_all_items(gate, wid: str) -> None:
    gate.write_inbox(wid, "A", "Body A")
    gate.write_inbox(wid, "B", "Body B")
    assert len(gate.list_inbox(wid)) >= 2

    gate.clear_inbox(wid)
    items = gate.list_inbox(wid)
    assert len(items) == 0


def test_clear_inbox_wildcard(gate, wid: str) -> None:
    gate.write_inbox(wid, "C", "Body C")
    gate.clear_inbox("*")
    items = gate.list_inbox(wid)
    assert len(items) == 0


def test_inbox_item_includes_trace_id(gate, wid: str) -> None:
    trace_id = str(uuid.uuid4())
    iid = gate.write_inbox(wid, "Traced", "Traced body", trace_id=trace_id)
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["trace_id"] == trace_id


def test_inbox_item_default_priority(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "Default Priority", "Body")
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["priority"] == "normal"


def test_inbox_item_custom_priority(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "High Priority", "Body", priority="high")
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["priority"] == "high"


def test_inbox_item_source(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "Source Test", "Body", source="agent")
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["source"] == "agent"


def test_inbox_item_default_source(gate, wid: str) -> None:
    iid = gate.write_inbox(wid, "Default Source", "Body")
    item = gate.read_inbox_item(iid)
    assert item is not None
    assert item["source"] == "system"
