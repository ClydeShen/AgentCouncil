import sys
from pathlib import Path

import pytest

# Add parent directory to path to import server
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import TOKEN, _events, _cursors


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
