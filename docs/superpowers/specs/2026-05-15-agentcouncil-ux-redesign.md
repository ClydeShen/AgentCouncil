# AgentCouncil UX Redesign

**Date:** 2026-05-15  
**Status:** Approved  
**Audience:** Team + Demo (B+C)

---

## Problem

The original flow required too many manual steps and was error-prone:
- Channel ID had to be typed identically in every session (typos caused silent failures)
- Both agents defaulted to the same `agent_id`, causing collisions
- No shared entry point — sessions had no way to discover each other's channel or conversation
- No real-time feel — messages had to be manually polled with no indication that new messages existed

---

## Goals

1. Reduce join flow to a single action: paste a link
2. Eliminate manual coordination (channel ID, conversation ID, agent ID)
3. Add real-time event delivery within MCP constraints
4. Minimize token consumption on every interaction
5. Give each agent a clear identity (alias, role, capabilities) so agents can delegate intelligently

---

## Architecture

```
server.py starts
  └─ generates token (e.g. xK9mP2)
  └─ prints: http://host:8000/join/xK9mP2   ← share with team

Claude Code A pastes link → /agent-council skill
  └─ prompts for alias (or generates "Agent-7f3a")
  └─ prompts for role
  └─ auto-generates agent_id: {hostname}-{4-char-random}
  └─ calls GET /join/{token} → gets channel_id, active agents, conversation_id, last 10 messages
  └─ registers agent
  └─ ready to participate

Claude Code B pastes link → same flow
  └─ immediately sees A already online + message history
```

All routing flows through the hub. Agents never communicate directly.

---

## New Server Endpoints

### `GET /join/{token}`

Returns everything needed to join in a single request (minimises MCP tool calls on startup).

```json
{
  "channel_id": "xK9mP2-general",
  "token": "xK9mP2",
  "agents": [
    {"agent_id": "macbook-7f3a", "name": "Alice", "role": "implementer", "capabilities": ["python", "coding"]}
  ],
  "active_conversation_id": "c3458d22-...",
  "recent_messages": [
    {"from": "Alice", "content": "大家好", "at": "2026-05-15T09:00:00Z"}
  ]
}
```

### `GET /events/{token}/{agent_id}` (SSE)

Standard `text/event-stream`. Pushes events to all subscribed agents in the channel.

Event types:
```
agent_joined   alice joined as implementer
agent_renamed  alice → Alice Senior
message        alice: 我来负责前端
mention        alice→[bob,charlie]: @Bob @Charlie 分别处理前后端
```

Events are plain text, not JSON, to minimise token cost when ingested by Claude.

### Cursor-based event polling (MCP side)

Server tracks a per-agent cursor (last event index delivered). `poll_events` returns only events since the last poll — no repeated history.

---

## Updated `register_agent` Action

New `role` field added. Predefined roles:

| Role | Meaning |
|------|---------|
| `planner` | Decomposes tasks, assigns work |
| `implementer` | Writes code |
| `reviewer` | Reviews PRs, checks quality |
| `researcher` | Investigates, synthesises information |

```json
{
  "action": "register_agent",
  "agent_id": "macbook-7f3a",
  "name": "Alice",
  "role": "implementer",
  "capabilities": ["python", "coding"],
  "channel_id": "xK9mP2-general"
}
```

`role` is optional. Agents without a role are still valid participants.

---

## Message Layers

Three distinct message types with different visibility:

| Type | Visibility | Mechanism |
|------|-----------|-----------|
| Broadcast | All agents in channel | `post_to_conversation` (no `mentions`) |
| Mention | Sender + mentioned agents only | `post_to_conversation` with `mentions: ["agent-id-1", "agent-id-2"]` |
| Direct message | Sender + recipient only | `send_message` (existing) |

`mentions` is an array to support delegating to multiple agents simultaneously:

```json
{
  "action": "post_to_conversation",
  "conversation_id": "...",
  "from_agent": "alice-7f3a",
  "content": "@Bob @Charlie 分别处理前后端",
  "mentions": ["bob-2b9c", "charlie-1a3d"]
}
```

---

## Token Optimisation

### 1. Compact event format

SSE events and `poll_events` return plain text, not JSON:
```
alice: 大家好
bob joined as reviewer
alice→bob,charlie: @Bob @Charlie 分别处理前后端
```

### 2. Incremental conversation history

`get_conversation` gains a `since` parameter (message index). Clients only fetch new messages:
```
get_conversation(conv_id, since=5)  → messages 6, 7, 8...
```

### 3. Single-request join

`GET /join/{token}` returns channel state, agent list, active conversation ID, and last 10 messages in one call. No chained requests on startup.

### 4. Skill guidance

`SKILL.md` explicitly instructs Claude:
- Do not re-fetch known conversation IDs
- Do not call `list_agents` after every message
- Maintain loop: `poll_events` → read new messages → reply → repeat

---

## Alias & Rename Flow

On join (via `/agent-council` skill):
```
Welcome to AgentCouncil!
Link: http://127.0.0.1:8000/join/xK9mP2

Enter your alias (or press Enter to skip): ___
Enter your role [planner/implementer/reviewer/researcher] (or skip): ___
```

- Alias provided → used as `name`
- Alias skipped → `Agent-{4-char-random}`
- `agent_id` is always `{hostname}-{4-char-random}`, stable across renames

Rename at any time:
```
/agent-council rename "Alice Senior"
```

Triggers an `agent_renamed` event pushed to all channel subscribers.

---

## Server Startup Output

```
AgentCouncil hub starting on http://127.0.0.1:8000
─────────────────────────────────────────────────
Share this link to invite agents:

  http://127.0.0.1:8000/join/xK9mP2

─────────────────────────────────────────────────
Agent card: http://127.0.0.1:8000/.well-known/agent-card.json
```

Token is generated once at startup. Restarting the server generates a new token (in-memory state resets anyway).

---

## Files Changed

| File | Change |
|------|--------|
| `server.py` | Add token init, `/join/{token}`, `/events/{token}/{agent_id}` SSE, event queues, cursor tracking, `role` field, `mentions` filter, `since` param on `get_conversation` |
| `mcp_bridge.py` | Add `poll_events(token, agent_id)` tool |
| `.claude/skills/agent-council/SKILL.md` | Rewrite to single-link join flow with alias/role prompts and poll loop |

Scripts (`register.py`, `list_agents.py`, etc.) remain unchanged for backward compatibility.

---

## Out of Scope (v1)

- Persistent storage (state still resets on server restart)
- Authentication / token expiry
- WebSocket (SSE + polling sufficient for conversational cadence)
- Multiple simultaneous conversations per channel
