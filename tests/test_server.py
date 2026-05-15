import sys
from pathlib import Path

import pytest

# Add parent directory to path to import server
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import TOKEN, _events, _cursors, _emit, _disabled, _agent_colors, _COLORS


def test_token_is_six_chars():
    assert len(TOKEN) == 6
    assert TOKEN.isalnum()


def test_event_store_starts_empty():
    assert isinstance(_events, list)


def test_cursor_store_starts_empty():
    assert isinstance(_cursors, dict)


from server import _dispatch, _events, _agents, _conversations


def setup_function():
    _events.clear()
    _agents.clear()
    _conversations.clear()
    _disabled.clear()
    _agent_colors.clear()


def test_register_emits_event():
    _dispatch({
        "action": "register_agent",
        "agent_id": "alice-1234",
        "name": "Alice",
        "role": "implementer",
        "capabilities": ["python"],
        "channel_id": "test-channel",
    })
    assert any("Alice joined" in e for e in _events)


def test_register_with_role_emits_role():
    _events.clear()
    _dispatch({
        "action": "register_agent",
        "agent_id": "bob-5678",
        "name": "Bob",
        "role": "reviewer",
        "capabilities": [],
        "channel_id": "test-channel",
    })
    assert any("reviewer" in e for e in _events)


def test_post_emits_broadcast_event():
    _events.clear()
    _agents["alice-1234"] = {"name": "Alice", "role": "implementer", "capabilities": [], "channel_id": "test-channel", "registered_at": "2026-01-01"}
    result = _dispatch({
        "action": "create_conversation",
        "channel_id": "test-channel",
        "name": "General",
        "participants": ["alice-1234"],
    })
    conv_id = result["conversation_id"]
    _dispatch({
        "action": "post_to_conversation",
        "conversation_id": conv_id,
        "from_agent": "alice-1234",
        "content": "hello everyone",
    })
    assert any("Alice" in e and "hello everyone" in e for e in _events)


def test_post_with_mentions_emits_mention_event():
    _events.clear()
    _agents["alice-1234"] = {"name": "Alice", "role": "implementer", "capabilities": [], "channel_id": "test-channel", "registered_at": "2026-01-01"}
    _agents["bob-5678"] = {"name": "Bob", "role": "reviewer", "capabilities": [], "channel_id": "test-channel", "registered_at": "2026-01-01"}
    result = _dispatch({
        "action": "create_conversation",
        "channel_id": "test-channel",
        "name": "Work",
        "participants": ["alice-1234", "bob-5678"],
    })
    conv_id = result["conversation_id"]
    _dispatch({
        "action": "post_to_conversation",
        "conversation_id": conv_id,
        "from_agent": "alice-1234",
        "content": "@Bob do this",
        "mentions": ["bob-5678"],
    })
    assert any("alice-1234→bob-5678" in e for e in _events)


from starlette.testclient import TestClient
from server import app, TOKEN, _agents, _inboxes, _conversations, _events, _dispatch


def test_join_invalid_token():
    client = TestClient(app)
    resp = client.get("/join/badtoken")
    assert resp.status_code == 404


def test_join_valid_token_returns_context():
    client = TestClient(app)
    resp = client.get(f"/join/{TOKEN}")
    assert resp.status_code == 200
    body = resp.json()
    assert "channel_id" in body
    assert "token" in body
    assert "agents" in body
    assert "active_conversation_id" in body
    assert "recent_messages" in body


def test_join_returns_recent_messages():
    _agents.clear()
    _inboxes.clear()
    _conversations.clear()
    _events.clear()
    client = TestClient(app)
    _agents["alice-1234"] = {
        "name": "Alice", "role": "implementer", "capabilities": [],
        "channel_id": f"{TOKEN}-general", "registered_at": "2026-01-01"
    }
    result = _dispatch({
        "action": "create_conversation",
        "channel_id": f"{TOKEN}-general",
        "name": "General",
        "participants": ["alice-1234"],
    })
    conv_id = result["conversation_id"]
    _dispatch({
        "action": "post_to_conversation",
        "conversation_id": conv_id,
        "from_agent": "alice-1234",
        "content": "hello",
    })
    resp = client.get(f"/join/{TOKEN}")
    body = resp.json()
    assert body["active_conversation_id"] == conv_id
    assert len(body["recent_messages"]) == 1
    assert body["recent_messages"][0]["content"] == "hello"


def test_poll_events_returns_new_events():
    _events.clear()
    _cursors.clear()
    _agents["alice-1234"] = {
        "name": "Alice", "role": "implementer", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01"
    }
    _emit("Alice: hello")
    _emit("Bob joined")
    result = _dispatch({"action": "poll_events", "agent_id": "alice-1234"})
    assert result["events"] == ["Alice: hello", "Bob joined"]
    assert result["cursor"] == 2


def test_poll_events_returns_only_new_events_after_cursor():
    _events.clear()
    _cursors.clear()
    _emit("event 1")
    _emit("event 2")
    _cursors["alice-1234"] = 2
    _emit("event 3")
    result = _dispatch({"action": "poll_events", "agent_id": "alice-1234"})
    assert result["events"] == ["event 3"]
    assert result["cursor"] == 3


def test_poll_events_filters_mentions():
    _events.clear()
    _cursors.clear()
    _emit("alice-1234→bob-5678: @Bob do this")
    _emit("Alice: hello everyone")
    result = _dispatch({"action": "poll_events", "agent_id": "alice-1234"})
    assert any("alice-1234→bob-5678" in e for e in result["events"])
    assert any("hello everyone" in e for e in result["events"])


def test_poll_events_mention_hidden_from_non_participants():
    _events.clear()
    _cursors.clear()
    _agents["charlie-9999"] = {
        "name": "Charlie", "role": "", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01"
    }
    _emit("alice-1234→bob-5678: @Bob secret task")
    result = _dispatch({"action": "poll_events", "agent_id": "charlie-9999"})
    assert result["events"] == []


def test_get_conversation_since():
    _conversations.clear()
    _agents["alice-1234"] = {
        "name": "Alice", "role": "implementer", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01"
    }
    result = _dispatch({
        "action": "create_conversation",
        "channel_id": "test-channel",
        "name": "Chat",
        "participants": [],
    })
    conv_id = result["conversation_id"]
    for i in range(5):
        _dispatch({
            "action": "post_to_conversation",
            "conversation_id": conv_id,
            "from_agent": "alice-1234",
            "content": f"msg {i}",
        })
    conv = _dispatch({"action": "get_conversation", "conversation_id": conv_id, "since": 3})
    assert len(conv["messages"]) == 2
    assert conv["messages"][0]["content"] == "msg 3"
    assert conv["messages"][1]["content"] == "msg 4"


def test_get_conversation_since_zero_returns_all():
    _conversations.clear()
    _agents["alice-1234"] = {
        "name": "Alice", "role": "implementer", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01"
    }
    result = _dispatch({
        "action": "create_conversation",
        "channel_id": "test-channel",
        "name": "Chat2",
        "participants": [],
    })
    conv_id = result["conversation_id"]
    for i in range(3):
        _dispatch({
            "action": "post_to_conversation",
            "conversation_id": conv_id,
            "from_agent": "alice-1234",
            "content": f"msg {i}",
        })
    conv = _dispatch({"action": "get_conversation", "conversation_id": conv_id, "since": 0})
    assert len(conv["messages"]) == 3


def test_mcp_endpoint_exists():
    with TestClient(app) as client:
        resp = client.get("/mcp")
        assert resp.status_code in (200, 405, 307, 406)


# ---------------------------------------------------------------------------
# unregister_agent tests
# ---------------------------------------------------------------------------

from server import _inboxes, _cursors


def test_unregister_removes_agent():
    _agents["dave-0001"] = {
        "name": "Dave", "role": "planner", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01",
    }
    result = _dispatch({"action": "unregister_agent", "agent_id": "dave-0001"})
    assert result == {"ok": True, "agent_id": "dave-0001"}
    assert "dave-0001" not in _agents


def test_unregister_clears_inbox():
    _agents["dave-0001"] = {
        "name": "Dave", "role": "planner", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01",
    }
    _inboxes["dave-0001"] = [{"id": "x", "from": "alice", "content": "hi", "at": "now"}]
    _dispatch({"action": "unregister_agent", "agent_id": "dave-0001"})
    assert "dave-0001" not in _inboxes


def test_unregister_clears_cursor():
    _agents["dave-0001"] = {
        "name": "Dave", "role": "planner", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01",
    }
    _cursors["dave-0001"] = 5
    _dispatch({"action": "unregister_agent", "agent_id": "dave-0001"})
    assert "dave-0001" not in _cursors


def test_unregister_emits_left_event():
    _events.clear()
    _agents["dave-0001"] = {
        "name": "Dave", "role": "planner", "capabilities": [],
        "channel_id": "test-channel", "registered_at": "2026-01-01",
    }
    _dispatch({"action": "unregister_agent", "agent_id": "dave-0001"})
    assert any("Dave left" in e for e in _events)


def test_unregister_unknown_agent_returns_error():
    result = _dispatch({"action": "unregister_agent", "agent_id": "nobody-9999"})
    assert result["ok"] is False
    assert "Unknown agent" in result["error"]


def test_register_assigns_color():
    _dispatch({
        "action": "register_agent",
        "agent_id": "alice-1",
        "name": "Alice",
        "role": "planner",
        "capabilities": [],
        "channel_id": "ch",
    })
    assert "alice-1" in _agent_colors
    assert _agent_colors["alice-1"] in _COLORS


def test_register_colors_round_robin():
    for i in range(9):
        _dispatch({
            "action": "register_agent",
            "agent_id": f"agent-{i}",
            "name": f"Agent{i}",
            "role": "",
            "capabilities": [],
            "channel_id": "ch",
        })
    # 9th agent (index 8) wraps around to _COLORS[0]
    assert _agent_colors["agent-8"] == _COLORS[0]
