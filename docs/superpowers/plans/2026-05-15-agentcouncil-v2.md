# AgentCouncil v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild AgentCouncil so any team member can join a shared AI agent channel by pasting one URL — no local processes, no manual coordination.

**Architecture:** `server.py` becomes a single process that exposes A2A, MCP, join, and SSE endpoints. `mcp_bridge.py` is deleted. Users configure `mcp.json` with the server URL and run `/agent-council` to join.

**Tech Stack:** Python 3.10+, a2a-sdk, FastMCP 3.x, Starlette, uvicorn, pytest, httpx

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `server.py` | Modify | Hub: A2A + MCP + SSE + join endpoint, all in one process |
| `mcp_bridge.py` | Delete | Merged into server.py |
| `examples/mcp_config.json` | Modify | Update URL to `:8000/mcp` |
| `.claude/skills/agent-council/SKILL.md` | Modify | Single-link join flow |
| `tests/test_server.py` | Create | Integration tests via Starlette TestClient |
| `pyproject.toml` | Modify | Add pytest + httpx dev deps |

---

## Task 1: Add pytest and httpx dev dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dev dependencies**

Edit `pyproject.toml` to add:

```toml
[project]
name = "agentcouncil"
version = "0.1.0"
description = "Universal multi-agent A2A hub with optional MCP bridge"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "a2a-sdk[http-server]>=1.0",
    "fastmcp>=3.0",
    "httpx>=0.27",
    "uvicorn>=0.30",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Sync dependencies**

```bash
uv sync --group dev
```

Expected: resolves and installs pytest and pytest-asyncio.

- [ ] **Step 3: Verify pytest works**

```bash
uv run pytest --version
```

Expected: `pytest 8.x.x`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pytest dev dependencies"
```

---

## Task 2: Add token generation and in-memory event store to server.py

**Files:**
- Modify: `server.py`

This task adds the token and event infrastructure that all later tasks depend on. No new endpoints yet.

- [ ] **Step 1: Write failing test**

Create `tests/test_server.py`:

```python
import pytest
from server import TOKEN, _events, _cursors

def test_token_is_six_chars():
    assert len(TOKEN) == 6
    assert TOKEN.isalnum()

def test_event_store_starts_empty():
    assert isinstance(_events, list)

def test_cursor_store_starts_empty():
    assert isinstance(_cursors, dict)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_server.py -v
```

Expected: ImportError — `TOKEN`, `_events`, `_cursors` not defined.

- [ ] **Step 3: Add token and event store to server.py**

Add after the existing in-memory store section (after `_conversations` definition):

```python
import random
import string

# ---------------------------------------------------------------------------
# Token + event store
# ---------------------------------------------------------------------------

TOKEN: str = "".join(random.choices(string.ascii_letters + string.digits, k=6))

_events: list[str] = []
# plain-text event log: "alice: message", "bob joined as reviewer", etc.

_cursors: dict[str, int] = {}
# agent_id -> last event index delivered via poll_events


def _emit(event: str) -> None:
    """Append a plain-text event to the channel log."""
    _events.append(event)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_server.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add token generation and event store"
```

---

## Task 3: Emit events on register_agent and post_to_conversation

**Files:**
- Modify: `server.py` (inside `_dispatch`)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
from server import _dispatch, _events

def setup_function():
    _events.clear()

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
    # create conversation first
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py -v -k "emits"
```

Expected: 4 FAILED.

- [ ] **Step 3: Add role field and emit calls to _dispatch**

Update the `register_agent` case in `_dispatch`:

```python
case "register_agent":
    agent_id = data["agent_id"]
    role = data.get("role", "")
    _agents[agent_id] = {
        "name": data["name"],
        "role": role,
        "capabilities": data.get("capabilities", []),
        "channel_id": data["channel_id"],
        "registered_at": _now(),
    }
    _inboxes.setdefault(agent_id, [])
    role_str = f" as {role}" if role else ""
    _emit(f"{data['name']} joined{role_str}")
    return {"ok": True, "agent_id": agent_id, "channel_id": data["channel_id"]}
```

Update the `post_to_conversation` case:

```python
case "post_to_conversation":
    conv = _conversations.get(data["conversation_id"])
    if not conv:
        return {"ok": False, "error": "Conversation not found"}
    agent_name = _agents.get(data["from_agent"], {}).get("name", data["from_agent"])
    mentions = data.get("mentions", [])
    conv["messages"].append({
        "from": data["from_agent"],
        "from_name": agent_name,
        "content": data["content"],
        "mentions": mentions,
        "at": _now(),
    })
    if mentions:
        targets = ",".join(mentions)
        _emit(f"{data['from_agent']}→{targets}: {data['content']}")
    else:
        _emit(f"{agent_name}: {data['content']}")
    return {"ok": True, "total_messages": len(conv["messages"])}
```

Also update `list_agents` to include `role` in the response:

```python
case "list_agents":
    channel_id = data["channel_id"]
    return [
        {"agent_id": aid, **info}
        for aid, info in _agents.items()
        if info["channel_id"] == channel_id
    ]
```

(No change needed — role is already in `info`.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: emit events on register and post, add role field"
```

---

## Task 4: Add GET /join/{token} endpoint

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server.py`:

```python
from starlette.testclient import TestClient
from server import app, TOKEN

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
    from server import _agents, _inboxes, _conversations, _events
    _agents.clear(); _inboxes.clear(); _conversations.clear(); _events.clear()
    client = TestClient(app)
    # register an agent and create a conversation
    _agents["alice-1234"] = {"name": "Alice", "role": "implementer", "capabilities": [], "channel_id": f"{TOKEN}-general", "registered_at": "2026-01-01"}
    result = _dispatch({"action": "create_conversation", "channel_id": f"{TOKEN}-general", "name": "General", "participants": ["alice-1234"]})
    conv_id = result["conversation_id"]
    _dispatch({"action": "post_to_conversation", "conversation_id": conv_id, "from_agent": "alice-1234", "content": "hello"})
    resp = client.get(f"/join/{TOKEN}")
    body = resp.json()
    assert body["active_conversation_id"] == conv_id
    assert len(body["recent_messages"]) == 1
    assert body["recent_messages"][0]["content"] == "hello"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py -v -k "join"
```

Expected: 3 FAILED — route not found.

- [ ] **Step 3: Add /join/{token} route to server.py**

Add this function before the `app = Starlette(...)` line:

```python
import json as _json
from starlette.requests import Request
from starlette.responses import JSONResponse

async def _join_handler(request: Request) -> JSONResponse:
    token = request.path_params["token"]
    if token != TOKEN:
        return JSONResponse({"error": "Invalid token"}, status_code=404)
    channel_id = f"{TOKEN}-general"
    agents = [
        {"agent_id": aid, "name": info["name"], "role": info.get("role", ""), "capabilities": info["capabilities"]}
        for aid, info in _agents.items()
        if info["channel_id"] == channel_id
    ]
    # find most recently created conversation in this channel
    active_conv_id = None
    recent_messages = []
    for conv_id, conv in _conversations.items():
        if conv["channel_id"] == channel_id:
            active_conv_id = conv_id
            recent_messages = conv["messages"][-10:]
    return JSONResponse({
        "channel_id": channel_id,
        "token": TOKEN,
        "agents": agents,
        "active_conversation_id": active_conv_id,
        "recent_messages": recent_messages,
    })
```

Update `app = Starlette(...)` to include the new route:

```python
from starlette.routing import Route

app = Starlette(
    routes=(
        create_agent_card_routes(AGENT_CARD)
        + create_jsonrpc_routes(_handler, rpc_url="/")
        + [Route("/join/{token}", _join_handler)]
    )
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v -k "join"
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add GET /join/{token} endpoint"
```

---

## Task 5: Add poll_events MCP tool and cursor tracking

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server.py`:

```python
from server import _dispatch, _events, _cursors

def test_poll_events_returns_new_events():
    _events.clear()
    _cursors.clear()
    _agents["alice-1234"] = {"name": "Alice", "role": "implementer", "capabilities": [], "channel_id": "test-channel", "registered_at": "2026-01-01"}
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
    _cursors["alice-1234"] = 2  # already seen both
    _emit("event 3")
    result = _dispatch({"action": "poll_events", "agent_id": "alice-1234"})
    assert result["events"] == ["event 3"]
    assert result["cursor"] == 3

def test_poll_events_filters_mentions():
    _events.clear()
    _cursors.clear()
    # mention event only for bob
    _emit("alice-1234→bob-5678: @Bob do this")
    # broadcast event
    _emit("Alice: hello everyone")
    result = _dispatch({"action": "poll_events", "agent_id": "alice-1234"})
    # alice is the sender of the mention, should see it
    assert any("alice-1234→bob-5678" in e for e in result["events"])
    # alice should see the broadcast
    assert any("hello everyone" in e for e in result["events"])

def test_poll_events_mention_hidden_from_non_participants():
    _events.clear()
    _cursors.clear()
    _agents["charlie-9999"] = {"name": "Charlie", "role": "", "capabilities": [], "channel_id": "test-channel", "registered_at": "2026-01-01"}
    # mention between alice and bob — charlie should not see it
    _emit("alice-1234→bob-5678: @Bob secret task")
    result = _dispatch({"action": "poll_events", "agent_id": "charlie-9999"})
    assert result["events"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py -v -k "poll"
```

Expected: 4 FAILED.

- [ ] **Step 3: Add poll_events case to _dispatch and _emit import**

Add the `poll_events` case to `_dispatch`:

```python
case "poll_events":
    agent_id = data["agent_id"]
    cursor = _cursors.get(agent_id, 0)
    new_events = _events[cursor:]
    visible = []
    for event in new_events:
        # mention events: "sender→target1,target2: content"
        if "→" in event.split(":")[0]:
            header = event.split(":")[0]  # e.g. "alice-1234→bob-5678"
            sender, targets_str = header.split("→")
            targets = targets_str.split(",")
            if agent_id == sender or agent_id in targets:
                visible.append(event)
        else:
            visible.append(event)
    _cursors[agent_id] = cursor + len(new_events)
    return {"events": visible, "cursor": _cursors[agent_id]}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v -k "poll"
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add poll_events action with cursor tracking and mention filtering"
```

---

## Task 6: Add get_conversation since parameter

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server.py`:

```python
def test_get_conversation_since():
    _conversations.clear()
    result = _dispatch({"action": "create_conversation", "channel_id": "test-channel", "name": "Chat", "participants": []})
    conv_id = result["conversation_id"]
    for i in range(5):
        _dispatch({"action": "post_to_conversation", "conversation_id": conv_id, "from_agent": "alice-1234", "content": f"msg {i}"})
    # fetch only messages after index 3
    conv = _dispatch({"action": "get_conversation", "conversation_id": conv_id, "since": 3})
    assert len(conv["messages"]) == 2
    assert conv["messages"][0]["content"] == "msg 3"
    assert conv["messages"][1]["content"] == "msg 4"

def test_get_conversation_since_zero_returns_all():
    _conversations.clear()
    result = _dispatch({"action": "create_conversation", "channel_id": "test-channel", "name": "Chat2", "participants": []})
    conv_id = result["conversation_id"]
    for i in range(3):
        _dispatch({"action": "post_to_conversation", "conversation_id": conv_id, "from_agent": "alice-1234", "content": f"msg {i}"})
    conv = _dispatch({"action": "get_conversation", "conversation_id": conv_id, "since": 0})
    assert len(conv["messages"]) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py -v -k "since"
```

Expected: 2 FAILED.

- [ ] **Step 3: Update get_conversation case in _dispatch**

```python
case "get_conversation":
    conv = _conversations.get(data["conversation_id"])
    if not conv:
        return {"ok": False, "error": "Conversation not found"}
    since = data.get("since", 0)
    result = dict(conv)
    result["messages"] = conv["messages"][since:]
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py -v -k "since"
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add since parameter to get_conversation"
```

---

## Task 7: Expose MCP endpoint in server.py

**Files:**
- Modify: `server.py`

This mounts a FastMCP server at `/mcp` alongside the existing A2A and join routes.

- [ ] **Step 1: Write failing test**

Add to `tests/test_server.py`:

```python
def test_mcp_endpoint_exists():
    client = TestClient(app)
    # FastMCP streamable-http responds to GET /mcp with 405 or 200
    resp = client.get("/mcp")
    assert resp.status_code in (200, 405, 307)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_server.py -v -k "mcp_endpoint"
```

Expected: FAILED — `/mcp` returns 404.

- [ ] **Step 3: Add FastMCP server with poll_events tool and mount at /mcp**

Add after the `_emit` function definition:

```python
from fastmcp import FastMCP as _FastMCP

_mcp = _FastMCP(
    name="AgentCouncil",
    instructions=(
        "Tools for the AgentCouncil multi-agent hub. "
        "Use poll_events to check for new messages since your last call. "
        "Use register_agent once at session start."
    ),
)


@_mcp.tool
def poll_events(agent_id: str) -> dict:
    """Retrieve new channel events since last poll. Returns compact plain-text lines.

    Call before every reply to get messages you may have missed.
    Mention events (sender→targets: content) are filtered — only visible to sender and mentioned agents.
    """
    return _dispatch({"action": "poll_events", "agent_id": agent_id})
```

Update `app = Starlette(...)` to mount the MCP app:

```python
from starlette.routing import Route, Mount

_mcp_app = _mcp.http_app(path="/")

app = Starlette(
    routes=(
        create_agent_card_routes(AGENT_CARD)
        + create_jsonrpc_routes(_handler, rpc_url="/")
        + [
            Route("/join/{token}", _join_handler),
            Mount("/mcp", app=_mcp_app),
        ]
    )
)
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/test_server.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Smoke test manually**

```bash
uv run python server.py &
sleep 1
curl -s http://127.0.0.1:8000/mcp | head -5
kill %1
```

Expected: response from FastMCP (not 404).

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: mount FastMCP at /mcp inside server.py"
```

---

## Task 8: Update examples/mcp_config.json and delete mcp_bridge.py

**Files:**
- Modify: `examples/mcp_config.json`
- Delete: `mcp_bridge.py`
- Modify: `.claude/mcp.json`

- [ ] **Step 1: Update mcp_config.json**

Replace content of `examples/mcp_config.json`:

```json
{
  "mcpServers": {
    "agent-council": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

- [ ] **Step 2: Update project mcp.json**

```bash
cp examples/mcp_config.json .claude/mcp.json
```

- [ ] **Step 3: Delete mcp_bridge.py**

```bash
git rm mcp_bridge.py
```

- [ ] **Step 4: Commit**

```bash
git add examples/mcp_config.json .claude/mcp.json
git commit -m "feat: merge MCP into server.py, delete mcp_bridge.py"
```

---

## Task 9: Update server startup output to print join URL

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Update the startup print block in __main__**

Replace the existing print lines in the `if __name__ == "__main__":` block:

```python
if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="AgentCouncil Hub")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"
    print(f"AgentCouncil hub starting on {base}")
    print("─" * 51)
    print("Share this link to invite agents:")
    print()
    print(f"  {base}/join/{TOKEN}")
    print()
    print("─" * 51)
    print(f"MCP endpoint:  {base}/mcp")
    print(f"Agent card:    {base}/.well-known/agent-card.json")
    uvicorn.run(app, host=args.host, port=args.port)
```

- [ ] **Step 2: Smoke test**

```bash
uv run python server.py &
sleep 1
curl -s http://127.0.0.1:8000/join/$(python -c "from server import TOKEN; print(TOKEN)")
kill %1
```

Expected: JSON with `channel_id`, `token`, `agents`, `active_conversation_id`, `recent_messages`.

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat: print join URL and MCP endpoint on startup"
```

---

## Task 10: Rewrite SKILL.md to single-link join flow

**Files:**
- Modify: `.claude/skills/agent-council/SKILL.md`

- [ ] **Step 1: Rewrite SKILL.md**

Replace the full content of `.claude/skills/agent-council/SKILL.md`:

```markdown
---
name: agent-council
description: Join the AgentCouncil multi-agent hub. Use when coordinating with other AI agents on a shared task. Paste the join link shared by the server admin to connect.
---

## Join

1. Ask the user: "Paste your AgentCouncil join link (e.g. http://server:8000/join/xK9mP2):"
2. Call `GET <join-link>` via Bash:
   ```bash
   curl -s <join-link>
   ```
   Save: `channel_id`, `active_conversation_id`, list of current agents.

3. Ask: "What's your alias? (press Enter to skip)"
   - If provided: use as `name`
   - If skipped: use `Agent-<4 random chars>`

4. Ask: "What's your role? [planner/implementer/reviewer/researcher] (press Enter to skip)"

5. Generate `agent_id`: `<hostname>-<4 random hex chars>`
   ```bash
   echo "$(hostname)-$(openssl rand -hex 2)"
   ```

6. Register via the hub's A2A endpoint:
   ```bash
   curl -s -X POST <base-url>/ \
     -H "Content-Type: application/json" \
     -H "A2A-Version: 1.0" \
     -d '{
       "jsonrpc":"2.0","id":1,"method":"SendMessage",
       "params":{"message":{"messageId":"<uuid>","role":"ROLE_USER",
         "parts":[{"data":{
           "action":"register_agent",
           "agent_id":"<agent_id>",
           "name":"<name>",
           "role":"<role>",
           "capabilities":[],
           "channel_id":"<channel_id>"
         }}]}}}'
   ```

7. Print current agents and last messages from the join response so the user sees the context.

8. If no active conversation exists, create one:
   ```bash
   curl -s -X POST <base-url>/ \
     -H "Content-Type: application/json" \
     -H "A2A-Version: 1.0" \
     -d '{
       "jsonrpc":"2.0","id":1,"method":"SendMessage",
       "params":{"message":{"messageId":"<uuid>","role":"ROLE_USER",
         "parts":[{"data":{
           "action":"create_conversation",
           "channel_id":"<channel_id>",
           "name":"General",
           "participants":["<agent_id>"]
         }}]}}}'
   ```

## Message Loop

**Before every reply**, poll for new events:
```bash
curl -s -X POST <base-url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"SendMessage",
    "params":{"message":{"messageId":"<uuid>","role":"ROLE_USER",
      "parts":[{"data":{
        "action":"poll_events",
        "agent_id":"<agent_id>"
      }}]}}}'
```

Read the `events` list. If non-empty, show them to the user before replying.

**To post a message:**
```bash
curl -s -X POST <base-url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"SendMessage",
    "params":{"message":{"messageId":"<uuid>","role":"ROLE_USER",
      "parts":[{"data":{
        "action":"post_to_conversation",
        "conversation_id":"<active_conversation_id>",
        "from_agent":"<agent_id>",
        "content":"<message>"
      }}]}}}'
```

**To @mention specific agents** (they alone will see this event):
Add `"mentions": ["<agent_id_1>", "<agent_id_2>"]` to the post payload.

**To rename yourself:**
Re-run `register_agent` with the same `agent_id` and new `name`.

## Token-saving rules

- Do NOT call `list_agents` after every message — use the join response's agent list.
- Do NOT re-fetch `active_conversation_id` — save it from the join response.
- Do NOT fetch full conversation history if you only need new messages — use `poll_events`.
- Use `get_conversation` with `"since": <N>` if you need partial history.
```

- [ ] **Step 2: Run a quick sanity check — start server and hit the join link**

```bash
uv run python server.py &
sleep 1
TOKEN=$(uv run python -c "from server import TOKEN; print(TOKEN)")
curl -s http://127.0.0.1:8000/join/$TOKEN | python -m json.tool
kill %1
```

Expected: valid JSON with all required fields.

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/test_server.py -v
```

Expected: all PASSED.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/agent-council/SKILL.md
git commit -m "feat: rewrite agent-council skill to single-link join flow"
```

---

## Task 11: Final integration smoke test

**Files:** none (validation only)

- [ ] **Step 1: Start server**

```bash
uv run python server.py
```

Expected output:
```
AgentCouncil hub starting on http://127.0.0.1:8000
───────────────────────────────────────────────────
Share this link to invite agents:

  http://127.0.0.1:8000/join/<TOKEN>

───────────────────────────────────────────────────
MCP endpoint:  http://127.0.0.1:8000/mcp
Agent card:    http://127.0.0.1:8000/.well-known/agent-card.json
```

- [ ] **Step 2: Hit the join link**

```bash
curl -s http://127.0.0.1:8000/join/<TOKEN> | python -m json.tool
```

Expected: JSON with `channel_id`, `token`, empty `agents`, null `active_conversation_id`.

- [ ] **Step 3: Register two agents and exchange a message**

```bash
# Register Alice
curl -s -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m1","role":"ROLE_USER","parts":[{"data":{"action":"register_agent","agent_id":"alice-0001","name":"Alice","role":"planner","capabilities":["planning"],"channel_id":"<TOKEN>-general"}}]}}}'

# Register Bob
curl -s -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m2","role":"ROLE_USER","parts":[{"data":{"action":"register_agent","agent_id":"bob-0002","name":"Bob","role":"implementer","capabilities":["coding"],"channel_id":"<TOKEN>-general"}}]}}}'

# Create conversation
curl -s -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m3","role":"ROLE_USER","parts":[{"data":{"action":"create_conversation","channel_id":"<TOKEN>-general","name":"General","participants":["alice-0001","bob-0002"]}}]}}}' | python -m json.tool
# note the conversation_id

# Post a message
curl -s -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m4","role":"ROLE_USER","parts":[{"data":{"action":"post_to_conversation","conversation_id":"<conv_id>","from_agent":"alice-0001","content":"Hi Bob, can you take the backend?"}}]}}}'

# Bob polls events
curl -s -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m5","role":"ROLE_USER","parts":[{"data":{"action":"poll_events","agent_id":"bob-0002"}}]}}}' | python -m json.tool
```

Expected: Bob's poll returns `"Alice: Hi Bob, can you take the backend?"`.

- [ ] **Step 4: Verify MCP endpoint**

```bash
curl -s http://127.0.0.1:8000/mcp
```

Expected: response from FastMCP (not 404).

- [ ] **Step 5: Run full test suite one final time**

```bash
uv run pytest tests/test_server.py -v
```

Expected: all PASSED.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "chore: AgentCouncil v2 complete — single-link join, MCP merged, poll_events"
```
