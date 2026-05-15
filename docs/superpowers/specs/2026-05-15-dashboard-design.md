# AgentCouncil Dashboard Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a local web dashboard to AgentCouncil so the server operator can monitor all agents and messages in real time, and can kick or disable individual agents.

**Architecture:** A new `/dashboard` route served by the existing Starlette app returns a single inline HTML page. Real-time updates use a `/dashboard/events` SSE stream that reuses the existing `_emit()` infrastructure. Agent management actions (kick, disable, enable) are POST routes that mutate server state and emit SSE events to all connected dashboards.

**Tech Stack:** Python / Starlette (existing), vanilla JS + EventSource (no framework, no build step), inline HTML (no separate files).

---

## Server-Side State

Two new module-level dicts added to `server.py`:

```python
_disabled: set[str] = set()          # agent_ids currently disabled
_agent_colors: dict[str, str] = {}   # agent_id → color hex, assigned on register
```

Color palette (8 colors, assigned round-robin by registration order):

```python
_COLORS = ["#e74c3c","#3498db","#2ecc71","#f39c12","#9b59b6","#1abc9c","#e67e22","#e91e63"]
```

---

## Behavior Rules

### Disable

When `agent_id in _disabled`:

| Action | Effect |
|--------|--------|
| `post_to_conversation` (from disabled) | Return `{"error": "agent disabled"}` |
| `send_message` (from disabled) | Return `{"error": "agent disabled"}` |
| `read_inbox` (disabled agent reads) | Return `[]`, discard accumulated inbox |
| `poll_events` (disabled agent polls) | Return `{"events": [], "cursor": current}` |

Messages sent **to** a disabled agent are silently dropped (not queued). On re-enable, the agent resumes from that point forward — no backfill.

### Kick

Calls the same logic as `unregister_agent`: removes from `_agents`, `_inbox`, `_cursors`, `_disabled`, `_agent_colors`, emits `agent_left` event.

---

## New Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/dashboard` | GET | Serves inline HTML dashboard |
| `/dashboard/events` | GET | SSE stream (text/event-stream) |
| `/dashboard/kick/{agent_id}` | POST | Unregisters agent immediately |
| `/dashboard/disable/{agent_id}` | POST | Adds to `_disabled`, emits `agent_disabled` |
| `/dashboard/enable/{agent_id}` | POST | Removes from `_disabled`, emits `agent_enabled` |

---

## SSE Event Format

All events are `data: <json>\n\n`. Event types:

| Type | Payload |
|------|---------|
| `snapshot` | `{agents: [{id, name, role, color, disabled}], messages: [...last 50...]}` |
| `agent_joined` | `{id, name, role, color}` |
| `agent_left` | `{id}` |
| `agent_disabled` | `{id}` |
| `agent_enabled` | `{id}` |
| `message` | `{from, from_id, to, content, at, color}` |

On initial SSE connection, server immediately pushes one `snapshot` event, then streams subsequent events.

The `/dashboard/events` endpoint reuses `_events` (the existing `asyncio.Queue` per SSE connection pattern), but is a separate generator so dashboard clients don't interfere with A2A SSE clients.

---

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│  AgentCouncil Dashboard  ·  channel: xK9mP2  🟢 3 live  │
├──────────────────┬──────────────────────────────────────┤
│ AGENTS           │  MESSAGES                            │
│                  │                                      │
│ ● Alice          │  12:01  Alice → Bob                  │
│   planner        │  "Let's start planning..."           │
│   [disable] [✕]  │                                      │
│                  │  12:02  Bob → all                    │
│ ⊘ Bob (disabled) │  "I'll handle the API layer"         │
│   implementer    │                                      │
│   [enable]  [✕]  │  12:03  ── Carol joined ──           │
│                  │                                      │
│ ● Carol          │                                      │
│   reviewer       │                                      │
│   [disable] [✕]  │                                      │
│                  │                                      │
└──────────────────┴──────────────────────────────────────┘
```

- Each agent has a unique color dot (from `_COLORS` palette)
- Disabled agents show `⊘` instead of `●`, name grayed out, button changes to `[enable]`
- Messages in the right panel use the sender's color for the name
- `[✕]` = kick, `[disable]`/`[enable]` = toggle disabled state

### Agent Detail Popup

Clicking an agent name opens an overlay popup:

```
┌──────────────────────────┐
│ Alice              [✕ close]
│ ──────────────────────── │
│ ID:    abc-123-...        │
│ Role:  planner            │
│ Channel: xK9mP2-general   │
│ Status: active            │
│                           │
│         [disable]  [kick] │
└──────────────────────────┘
```

---

## Frontend Implementation

Single inline HTML string in `server.py`. No external files, no CDN dependencies.

Structure:
- `<style>` block: minimal CSS, two-column layout, color vars
- `<div id="agents">` + `<div id="messages">`: updated by JS
- `<div id="popup">`: hidden overlay, shown on agent click
- `<script>` block:
  - `new EventSource('/dashboard/events')` — handles `snapshot`, `agent_*`, `message` events
  - `renderAgents()` / `appendMessage()` — DOM manipulation
  - `kick(id)` / `disable(id)` / `enable(id)` — `fetch` POST calls
  - `showPopup(agent)` / `closePopup()` — popup toggle

State held in JS:
```js
let agents = {}   // id → {name, role, color, disabled}
let messages = [] // [{from, from_id, to, content, at, color}]
```

---

## Integration Points in server.py

1. **`register_agent`**: assign color from `_COLORS[len(_agent_colors) % 8]`, store in `_agent_colors[agent_id]`, emit `agent_joined` with color.
2. **`unregister_agent`**: remove from `_agent_colors` and `_disabled`, emit `agent_left`.
3. **`post_to_conversation`** / **`send_message`**: check `from_agent in _disabled` at top, return error early.
4. **`read_inbox`** / **`poll_events`**: check `agent_id in _disabled`, return empty.
5. **`_emit()`**: fan out to both A2A SSE clients and dashboard SSE clients.
6. New `_dash_queues: list[asyncio.Queue]` — separate from existing `_queues` to avoid cross-contamination.

---

## What This Does NOT Do

- No auth (local only, same as the rest of the hub)
- No message filtering or search
- No conversation selector — shows all messages across all conversations in one stream
- No persistence — state resets on server restart
