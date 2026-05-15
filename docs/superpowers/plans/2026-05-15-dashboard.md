# AgentCouncil Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real-time local web dashboard at `/dashboard` that shows all agents and messages, lets the operator disable/re-enable agents, and kick them out.

**Architecture:** Three additions to `server.py`: (1) new in-memory state (`_disabled`, `_agent_colors`, `_dash_queues`), (2) five new Starlette routes (`/dashboard`, `/dashboard/events`, `/dashboard/kick/{id}`, `/dashboard/disable/{id}`, `/dashboard/enable/{id}`), (3) disable-guard checks inserted into existing `_dispatch` cases. The frontend is a single inline HTML string served by the `/dashboard` route — vanilla JS with `EventSource`, no framework, no build step.

**Tech Stack:** Python / Starlette (existing), asyncio, vanilla JS + EventSource, inline HTML.

---

## File Structure

- **Modify:** `server.py` — all changes go here
- **Modify:** `tests/test_server.py` — add tests for new behaviour

---

### Task 1: New state + color assignment on register

**Files:**
- Modify: `server.py:54-78` (in-memory store and `_emit`)
- Modify: `server.py:208-223` (`register_agent` case in `_dispatch`)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py` after the existing imports and `setup_function`:

```python
from server import _disabled, _agent_colors, _COLORS


def setup_function():
    _events.clear()
    _agents.clear()
    _conversations.clear()
    _disabled.clear()
    _agent_colors.clear()


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py::test_register_assigns_color tests/test_server.py::test_register_colors_round_robin -v
```

Expected: `ImportError` or `AttributeError` — `_disabled`, `_agent_colors`, `_COLORS` don't exist yet.

- [ ] **Step 3: Add state and constants to server.py**

After line 73 (`_cursors: dict[str, int] = {}`), add:

```python
_disabled: set[str] = set()
# agent_ids currently disabled — cannot send or receive messages

_agent_colors: dict[str, str] = {}
# agent_id → hex color, assigned on register

_COLORS: list[str] = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#e91e63",
]

_dash_queues: list = []
# asyncio.Queue instances for /dashboard/events SSE connections
```

- [ ] **Step 4: Assign color in register_agent case**

In `_dispatch`, `register_agent` case (around line 208), add color assignment right after storing to `_agents`. Replace the `_agents[agent_id] = {...}` block:

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
    _agent_colors[agent_id] = _COLORS[len(_agent_colors) % len(_COLORS)]
    role_str = f" as {role}" if role else ""
    _emit(f"{data['name']} joined{role_str}")
    log.info("[REGISTER] agent_id=%s name=%r role=%r channel=%s",
             agent_id, data["name"], role, data["channel_id"])
    return {"ok": True, "agent_id": agent_id, "channel_id": data["channel_id"]}
```

- [ ] **Step 5: Also clear color on unregister**

In the `unregister_agent` case (around line 324), after `_cursors.pop(agent_id, None)` add:

```python
_agent_colors.pop(agent_id, None)
_disabled.discard(agent_id)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py::test_register_assigns_color tests/test_server.py::test_register_colors_round_robin -v
```

Expected: PASS

- [ ] **Step 7: Run full suite to check no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 8: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: agent color assignment and disabled/dash state"
```

---

### Task 2: Disable guards in _dispatch

**Files:**
- Modify: `server.py` — `send_message`, `post_to_conversation`, `read_inbox`, `poll_events` cases
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

```python
def test_disabled_agent_cannot_post():
    _dispatch({
        "action": "register_agent", "agent_id": "alice-1", "name": "Alice",
        "role": "", "capabilities": [], "channel_id": "ch",
    })
    conv = _dispatch({
        "action": "create_conversation", "channel_id": "ch",
        "name": "general", "participants": ["alice-1"],
    })
    _disabled.add("alice-1")
    result = _dispatch({
        "action": "post_to_conversation",
        "conversation_id": conv["conversation_id"],
        "from_agent": "alice-1",
        "content": "hello",
        "mentions": [],
    })
    assert result.get("ok") is False
    assert "disabled" in result.get("error", "")


def test_disabled_agent_cannot_send_dm():
    _dispatch({
        "action": "register_agent", "agent_id": "alice-1", "name": "Alice",
        "role": "", "capabilities": [], "channel_id": "ch",
    })
    _dispatch({
        "action": "register_agent", "agent_id": "bob-1", "name": "Bob",
        "role": "", "capabilities": [], "channel_id": "ch",
    })
    _disabled.add("alice-1")
    result = _dispatch({
        "action": "send_message",
        "from_agent": "alice-1",
        "to_agent": "bob-1",
        "content": "hello",
    })
    assert result.get("ok") is False
    assert "disabled" in result.get("error", "")


def test_disabled_agent_read_inbox_returns_empty():
    _dispatch({
        "action": "register_agent", "agent_id": "alice-1", "name": "Alice",
        "role": "", "capabilities": [], "channel_id": "ch",
    })
    _inboxes["alice-1"] = [{"id": "x", "from": "b", "content": "hi", "at": "now"}]
    _disabled.add("alice-1")
    result = _dispatch({"action": "read_inbox", "agent_id": "alice-1"})
    assert result == []
    # inbox is discarded
    assert _inboxes.get("alice-1") == []


def test_disabled_agent_poll_events_returns_empty():
    _dispatch({
        "action": "register_agent", "agent_id": "alice-1", "name": "Alice",
        "role": "", "capabilities": [], "channel_id": "ch",
    })
    _emit("some event")
    _disabled.add("alice-1")
    result = _dispatch({"action": "poll_events", "agent_id": "alice-1"})
    assert result["events"] == []
```

Add `from server import _inboxes` to the imports at top of test file (it's not imported yet).

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py::test_disabled_agent_cannot_post tests/test_server.py::test_disabled_agent_cannot_send_dm tests/test_server.py::test_disabled_agent_read_inbox_returns_empty tests/test_server.py::test_disabled_agent_poll_events_returns_empty -v
```

Expected: all FAIL (no disable guards yet).

- [ ] **Step 3: Add disable guards to _dispatch**

In `post_to_conversation` case, add at the very top of the case (before the `conv = ...` lookup):

```python
case "post_to_conversation":
    if data["from_agent"] in _disabled:
        return {"ok": False, "error": "agent disabled"}
    conv = _conversations.get(data["conversation_id"])
    # ... rest unchanged
```

In `send_message` case, add after the `to` assignment:

```python
case "send_message":
    if data["from_agent"] in _disabled:
        return {"ok": False, "error": "agent disabled"}
    to = data["to_agent"]
    # ... rest unchanged
```

In `read_inbox` case, replace the body:

```python
case "read_inbox":
    agent_id = data["agent_id"]
    if agent_id in _disabled:
        _inboxes[agent_id] = []
        return []
    msgs = _inboxes.get(agent_id, [])
    _inboxes[agent_id] = []
    log.info("[INBOX] agent_id=%s cleared %d message(s)", agent_id, len(msgs))
    return msgs
```

In `poll_events` case, add at the top:

```python
case "poll_events":
    agent_id = data["agent_id"]
    if agent_id in _disabled:
        return {"events": [], "cursor": _cursors.get(agent_id, 0)}
    cursor = _cursors.get(agent_id, 0)
    # ... rest unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py::test_disabled_agent_cannot_post tests/test_server.py::test_disabled_agent_cannot_send_dm tests/test_server.py::test_disabled_agent_read_inbox_returns_empty tests/test_server.py::test_disabled_agent_poll_events_returns_empty -v
```

Expected: all PASS

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: disable guards in dispatch — blocked agents cannot send or receive"
```

---

### Task 3: Dashboard management routes (kick / disable / enable)

**Files:**
- Modify: `server.py` — add `_dash_emit`, three route handlers, register in `app`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

These tests use `starlette.testclient.TestClient`. Add to test file:

```python
from starlette.testclient import TestClient
from server import app, _disabled as _dis


def test_dashboard_kick_removes_agent():
    with TestClient(app) as client:
        _dispatch({
            "action": "register_agent", "agent_id": "alice-1", "name": "Alice",
            "role": "", "capabilities": [], "channel_id": f"{TOKEN}-general",
        })
        assert "alice-1" in _agents
        resp = client.post("/dashboard/kick/alice-1")
        assert resp.status_code == 200
        assert "alice-1" not in _agents


def test_dashboard_disable_sets_flag():
    with TestClient(app) as client:
        _dispatch({
            "action": "register_agent", "agent_id": "bob-1", "name": "Bob",
            "role": "", "capabilities": [], "channel_id": f"{TOKEN}-general",
        })
        resp = client.post("/dashboard/disable/bob-1")
        assert resp.status_code == 200
        assert "bob-1" in _dis


def test_dashboard_enable_clears_flag():
    with TestClient(app) as client:
        _dis.add("bob-1")
        resp = client.post("/dashboard/enable/bob-1")
        assert resp.status_code == 200
        assert "bob-1" not in _dis
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_server.py::test_dashboard_kick_removes_agent tests/test_server.py::test_dashboard_disable_sets_flag tests/test_server.py::test_dashboard_enable_clears_flag -v
```

Expected: FAIL with 404 (routes don't exist).

- [ ] **Step 3: Add _dash_emit helper and three route handlers**

Add after the `_emit` function (around line 79):

```python
def _dash_emit(event_type: str, payload: dict) -> None:
    import json
    import asyncio
    data = json.dumps({"type": event_type, **payload})
    for q in list(_dash_queues):
        try:
            asyncio.get_event_loop().call_soon_threadsafe(q.put_nowait, data)
        except Exception:
            pass
```

Add before the `_join_handler` function (around line 405):

```python
async def _dashboard_kick(request: Request) -> JSONResponse:
    agent_id = request.path_params["agent_id"]
    result = _dispatch({"action": "unregister_agent", "agent_id": agent_id})
    if result.get("ok"):
        _dash_emit("agent_left", {"id": agent_id})
    return JSONResponse(result)


async def _dashboard_disable(request: Request) -> JSONResponse:
    agent_id = request.path_params["agent_id"]
    if agent_id not in _agents:
        return JSONResponse({"ok": False, "error": f"Unknown agent: {agent_id}"}, status_code=404)
    _disabled.add(agent_id)
    log.info("[DISABLE] agent_id=%s", agent_id)
    _dash_emit("agent_disabled", {"id": agent_id})
    return JSONResponse({"ok": True, "agent_id": agent_id})


async def _dashboard_enable(request: Request) -> JSONResponse:
    agent_id = request.path_params["agent_id"]
    _disabled.discard(agent_id)
    log.info("[ENABLE] agent_id=%s", agent_id)
    _dash_emit("agent_enabled", {"id": agent_id})
    return JSONResponse({"ok": True, "agent_id": agent_id})
```

- [ ] **Step 4: Register routes in app**

In the `app = Starlette(...)` routes list, add the three new routes after `Route("/join/{token}", _join_handler)`:

```python
Route("/dashboard/kick/{agent_id}", _dashboard_kick, methods=["POST"]),
Route("/dashboard/disable/{agent_id}", _dashboard_disable, methods=["POST"]),
Route("/dashboard/enable/{agent_id}", _dashboard_enable, methods=["POST"]),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_server.py::test_dashboard_kick_removes_agent tests/test_server.py::test_dashboard_disable_sets_flag tests/test_server.py::test_dashboard_enable_clears_flag -v
```

Expected: all PASS

- [ ] **Step 6: Run full suite**

```bash
uv run pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: dashboard kick/disable/enable routes"
```

---

### Task 4: SSE endpoint /dashboard/events

**Files:**
- Modify: `server.py` — add `_dashboard_events` handler, register route, emit SSE events from `_dispatch`

The SSE endpoint streams JSON events to all connected dashboard clients. It uses `asyncio.Queue` (one per connection) stored in `_dash_queues`.

- [ ] **Step 1: Add _dashboard_events handler**

Add after `_dashboard_enable` handler:

```python
async def _dashboard_events(request: Request) -> None:
    import asyncio
    import json
    from starlette.responses import StreamingResponse

    queue: asyncio.Queue = asyncio.Queue()
    _dash_queues.append(queue)

    # Send initial snapshot
    channel_id = f"{TOKEN}-general"
    agents_snapshot = [
        {
            "id": aid,
            "name": info["name"],
            "role": info.get("role", ""),
            "color": _agent_colors.get(aid, _COLORS[0]),
            "disabled": aid in _disabled,
        }
        for aid, info in _agents.items()
        if info["channel_id"] == channel_id
    ]
    messages_snapshot = []
    for conv in _conversations.values():
        if conv["channel_id"] == channel_id:
            for m in conv["messages"][-50:]:
                from_id = m["from"]
                messages_snapshot.append({
                    "from": m.get("from_name", from_id),
                    "from_id": from_id,
                    "to": ",".join(m.get("mentions", [])) or "all",
                    "content": m["content"],
                    "at": m["at"],
                    "color": _agent_colors.get(from_id, _COLORS[0]),
                })

    snapshot = json.dumps({
        "type": "snapshot",
        "agents": agents_snapshot,
        "messages": messages_snapshot,
    })

    async def generator():
        yield f"data: {snapshot}\n\n"
        try:
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {data}\n\n"
        except asyncio.TimeoutError:
            yield "data: {\"type\":\"ping\"}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _dash_queues.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 2: Register route in app**

Add after the disable/enable routes:

```python
Route("/dashboard/events", _dashboard_events),
```

- [ ] **Step 3: Emit agent_joined from register_agent in _dispatch**

In the `register_agent` case, after `_emit(...)`, add:

```python
_dash_emit("agent_joined", {
    "id": agent_id,
    "name": data["name"],
    "role": role,
    "color": _agent_colors[agent_id],
})
```

- [ ] **Step 4: Emit agent_left from unregister_agent in _dispatch**

In the `unregister_agent` case, after `_emit(...)`, add:

```python
_dash_emit("agent_left", {"id": agent_id})
```

- [ ] **Step 5: Emit message from post_to_conversation in _dispatch**

In `post_to_conversation`, after appending to `conv["messages"]`, add:

```python
_dash_emit("message", {
    "from": agent_name,
    "from_id": data["from_agent"],
    "to": ",".join(mentions) if mentions else "all",
    "content": data["content"],
    "at": conv["messages"][-1]["at"],
    "color": _agent_colors.get(data["from_agent"], _COLORS[0]),
})
```

- [ ] **Step 6: Emit message from send_message (DM) in _dispatch**

In `send_message`, after appending to `_inboxes`, add:

```python
_dash_emit("message", {
    "from": data["from_agent"],
    "from_id": data["from_agent"],
    "to": to,
    "content": data["content"],
    "at": msg["at"],
    "color": _agent_colors.get(data["from_agent"], _COLORS[0]),
})
```

- [ ] **Step 7: Run full suite**

```bash
uv run pytest tests/ -v
```

Expected: all pass (no new tests needed for SSE — it's an async streaming endpoint, tested manually in Task 5).

- [ ] **Step 8: Commit**

```bash
git add server.py
git commit -m "feat: dashboard SSE events endpoint with snapshot on connect"
```

---

### Task 5: Dashboard HTML page

**Files:**
- Modify: `server.py` — add `_dashboard_html` handler with inline HTML, register route

- [ ] **Step 1: Add the HTML handler**

Add after `_dashboard_events`:

```python
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AgentCouncil Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: monospace; font-size: 13px; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
  #header { padding: 10px 16px; background: #16213e; border-bottom: 1px solid #333; display: flex; align-items: center; gap: 16px; }
  #header h1 { font-size: 14px; color: #a0c4ff; }
  #status { font-size: 12px; color: #888; }
  #main { display: flex; flex: 1; overflow: hidden; }
  #agents-panel { width: 220px; border-right: 1px solid #333; display: flex; flex-direction: column; }
  #agents-title { padding: 8px 12px; font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #222; }
  #agents-list { flex: 1; overflow-y: auto; padding: 8px 0; }
  .agent { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #1a1a2e; }
  .agent:hover { background: #1e2a3a; }
  .agent.disabled { opacity: 0.45; }
  .agent-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
  .agent-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .agent-name { font-weight: bold; font-size: 12px; }
  .agent-role { font-size: 11px; color: #888; margin-bottom: 6px; }
  .agent-actions { display: flex; gap: 6px; }
  .btn { font-family: monospace; font-size: 11px; padding: 2px 7px; border: 1px solid #444; background: #222; color: #ccc; cursor: pointer; border-radius: 2px; }
  .btn:hover { background: #333; }
  .btn-kick { border-color: #c0392b; color: #e74c3c; }
  .btn-kick:hover { background: #2a1a1a; }
  .btn-disable { border-color: #555; }
  .btn-enable { border-color: #2ecc71; color: #2ecc71; }
  #messages-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  #messages-title { padding: 8px 12px; font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #222; }
  #messages-list { flex: 1; overflow-y: auto; padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }
  .msg { display: flex; flex-direction: column; gap: 2px; }
  .msg-header { font-size: 11px; color: #666; }
  .msg-sender { font-weight: bold; }
  .msg-system { font-style: italic; color: #666; font-size: 12px; text-align: center; padding: 4px 0; }
  .msg-content { font-size: 12px; color: #ccc; padding-left: 4px; border-left: 2px solid #333; }
  #popup-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 100; align-items: center; justify-content: center; }
  #popup-overlay.visible { display: flex; }
  #popup { background: #16213e; border: 1px solid #333; padding: 20px; min-width: 280px; border-radius: 4px; }
  #popup h2 { font-size: 14px; margin-bottom: 12px; }
  #popup table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
  #popup td { padding: 3px 0; font-size: 12px; }
  #popup td:first-child { color: #888; width: 90px; }
  #popup-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
</head>
<body>
<div id="header">
  <h1>AgentCouncil Dashboard</h1>
  <span id="status">connecting...</span>
</div>
<div id="main">
  <div id="agents-panel">
    <div id="agents-title">Agents <span id="agent-count"></span></div>
    <div id="agents-list"></div>
  </div>
  <div id="messages-panel">
    <div id="messages-title">Messages</div>
    <div id="messages-list"></div>
  </div>
</div>
<div id="popup-overlay">
  <div id="popup">
    <h2 id="popup-name"></h2>
    <table id="popup-table"></table>
    <div id="popup-actions">
      <button class="btn" onclick="closePopup()">close</button>
      <button class="btn btn-disable" id="popup-toggle-btn"></button>
      <button class="btn btn-kick" id="popup-kick-btn">kick</button>
    </div>
  </div>
</div>
<script>
  let agents = {};

  function ts(iso) {
    return iso ? iso.slice(11, 16) : '';
  }

  function renderAgents() {
    const list = document.getElementById('agents-list');
    list.innerHTML = '';
    const arr = Object.values(agents);
    document.getElementById('agent-count').textContent = '(' + arr.filter(a => !a.disabled).length + ' live)';
    arr.forEach(a => {
      const div = document.createElement('div');
      div.className = 'agent' + (a.disabled ? ' disabled' : '');
      div.innerHTML = `
        <div class="agent-header">
          <span class="agent-dot" style="background:${a.color}"></span>
          <span class="agent-name" onclick="showPopup('${a.id}')" style="cursor:pointer">${a.name}</span>
        </div>
        <div class="agent-role">${a.role || 'no role'}</div>
        <div class="agent-actions">
          ${a.disabled
            ? `<button class="btn btn-enable" onclick="enableAgent('${a.id}')">enable</button>`
            : `<button class="btn btn-disable" onclick="disableAgent('${a.id}')">disable</button>`
          }
          <button class="btn btn-kick" onclick="kickAgent('${a.id}')">&#x2715;</button>
        </div>`;
      list.appendChild(div);
    });
  }

  function appendMessage(m) {
    const list = document.getElementById('messages-list');
    const div = document.createElement('div');
    if (m.system) {
      div.className = 'msg-system';
      div.textContent = '── ' + m.content + ' ──';
    } else {
      div.className = 'msg';
      const toLabel = m.to && m.to !== 'all' ? ` → ${m.to}` : ' → all';
      div.innerHTML = `
        <div class="msg-header">
          <span class="msg-sender" style="color:${m.color}">${m.from}</span>${toLabel}
          <span style="margin-left:8px">${ts(m.at)}</span>
        </div>
        <div class="msg-content">${m.content.replace(/</g,'&lt;')}</div>`;
    }
    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
  }

  function kickAgent(id) {
    if (!confirm('Kick ' + (agents[id]?.name || id) + '?')) return;
    fetch('/dashboard/kick/' + id, {method:'POST'});
  }

  function disableAgent(id) {
    fetch('/dashboard/disable/' + id, {method:'POST'});
  }

  function enableAgent(id) {
    fetch('/dashboard/enable/' + id, {method:'POST'});
  }

  function showPopup(id) {
    const a = agents[id];
    if (!a) return;
    document.getElementById('popup-name').textContent = a.name;
    document.getElementById('popup-table').innerHTML = `
      <tr><td>ID</td><td>${a.id}</td></tr>
      <tr><td>Role</td><td>${a.role || '—'}</td></tr>
      <tr><td>Status</td><td>${a.disabled ? 'disabled' : 'active'}</td></tr>`;
    const toggleBtn = document.getElementById('popup-toggle-btn');
    if (a.disabled) {
      toggleBtn.textContent = 'enable';
      toggleBtn.className = 'btn btn-enable';
      toggleBtn.onclick = () => { enableAgent(id); closePopup(); };
    } else {
      toggleBtn.textContent = 'disable';
      toggleBtn.className = 'btn btn-disable';
      toggleBtn.onclick = () => { disableAgent(id); closePopup(); };
    }
    document.getElementById('popup-kick-btn').onclick = () => { kickAgent(id); closePopup(); };
    document.getElementById('popup-overlay').classList.add('visible');
  }

  function closePopup() {
    document.getElementById('popup-overlay').classList.remove('visible');
  }

  document.getElementById('popup-overlay').addEventListener('click', e => {
    if (e.target === e.currentTarget) closePopup();
  });

  const es = new EventSource('/dashboard/events');

  es.addEventListener('message', e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;

    if (msg.type === 'snapshot') {
      msg.agents.forEach(a => { agents[a.id] = a; });
      renderAgents();
      msg.messages.forEach(appendMessage);
      document.getElementById('status').textContent = 'connected · channel: TOKEN_PLACEHOLDER';
    } else if (msg.type === 'agent_joined') {
      agents[msg.id] = {id: msg.id, name: msg.name, role: msg.role, color: msg.color, disabled: false};
      renderAgents();
      appendMessage({system: true, content: msg.name + ' joined'});
    } else if (msg.type === 'agent_left') {
      const name = agents[msg.id]?.name || msg.id;
      delete agents[msg.id];
      renderAgents();
      appendMessage({system: true, content: name + ' left'});
    } else if (msg.type === 'agent_disabled') {
      if (agents[msg.id]) { agents[msg.id].disabled = true; renderAgents(); }
    } else if (msg.type === 'agent_enabled') {
      if (agents[msg.id]) { agents[msg.id].disabled = false; renderAgents(); }
    } else if (msg.type === 'message') {
      appendMessage(msg);
    }
  });

  es.onerror = () => {
    document.getElementById('status').textContent = 'disconnected — retrying...';
  };
</script>
</body>
</html>"""


async def _dashboard_html(request: Request):
    from starlette.responses import HTMLResponse
    html = _DASHBOARD_HTML.replace("TOKEN_PLACEHOLDER", TOKEN)
    return HTMLResponse(html)
```

- [ ] **Step 2: Register route in app**

Add before the `/dashboard/events` route:

```python
Route("/dashboard", _dashboard_html),
```

- [ ] **Step 3: Print dashboard URL on startup**

In the `__main__` block, after the MCP endpoint print line, add:

```python
print(f"Dashboard:     {base}/dashboard")
```

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Manual smoke test**

```bash
make start
# open http://127.0.0.1:8000/dashboard in browser
# verify: page loads, shows "connected · channel: <token>"
# from another terminal: uv run python -c "
# import httpx, json
# r = httpx.get('http://127.0.0.1:8000/join/TOKEN')
# print(r.json())
# "
```

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "feat: dashboard HTML page with real-time SSE updates"
```

---

### Task 6: Update CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add v0.3.0 entry**

Add above the `## [0.2.0]` line:

```markdown
## [0.3.0] - 2026-05-15

### Added
- Local web dashboard at `/dashboard` — real-time view of agents and messages
- Agent color coding: each agent gets a distinct color from an 8-color palette, shown in dashboard and message headers
- Disable/enable agents from dashboard — disabled agents cannot send or receive messages; re-enabling resumes from that point (no backfill)
- Kick agents from dashboard — calls `unregister_agent` and emits departure event
- `/dashboard/events` SSE stream — pushes `snapshot`, `agent_joined`, `agent_left`, `agent_disabled`, `agent_enabled`, `message` events
- `/dashboard/kick/{agent_id}`, `/dashboard/disable/{agent_id}`, `/dashboard/enable/{agent_id}` POST routes
- Dashboard URL printed on server startup
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add v0.3.0 changelog entry for dashboard"
```
