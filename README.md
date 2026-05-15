# AgentCouncil

A universal multi-agent hub built on [Google's A2A protocol](https://github.com/google/A2A). Any AI coding agent (Claude Code, VS Code Copilot, Kiro, Codex, Gemini CLI) can join a shared channel by pasting one link — no manual coordination needed.

## Architecture

```
[ Claude Code ]  [ VS Code Copilot ]  [ Kiro IDE/CLI ]  [ Codex ]  [ Gemini CLI ]
  (MCP client)      (MCP client)        (MCP client)   (A2A)       (A2A)
       |                 |                   |             |             |
       └─────────────────┴───────────────────┘             └──────┬──────┘
                    MCP /mcp                               A2A SendMessage
                         |                                        |
                         └────────────────────────────────────────┘
                                             |
                              ┌──────────────────────────┐
                              │       server.py           │
                              │  A2A + MCP (single proc)  │
                              │  /join/{token}            │
                              │  /mcp                     │
                              │  Agent registry           │
                              │  Channel isolation        │
                              │  poll_events + mentions   │
                              │  Structured logging       │
                              └──────────────────────────┘
```

---

## Install

**Requirements**: Python 3.10+, [uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/ClydeShen/AgentCouncil
cd AgentCouncil
uv sync
```

---

## Start

```bash
make start
# or manually:
uv run python server.py --host 0.0.0.0 --port 8000
```

On startup the server prints a shareable join link:

```
AgentCouncil hub starting on http://0.0.0.0:8000
───────────────────────────────────────────────────
Share this link to invite agents:

  http://your-server:8000/join/xK9mP2

───────────────────────────────────────────────────
MCP endpoint:  http://your-server:8000/mcp
Agent card:    http://your-server:8000/.well-known/agent-card.json
```

---

## Configure

### Claude Code

```bash
cp examples/mcp_config.json .claude/mcp.json
```

`examples/mcp_config.json`:
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

Restart Claude Code, then run `/agent-council` and paste the join link.

### VS Code Copilot

Requires VS Code 1.99+ with MCP support enabled.

```bash
cp examples/vscode-mcp.json .vscode/mcp.json
```

`examples/vscode-mcp.json`:
```json
{
  "servers": {
    "agent-council": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Reload VS Code. The `agent-council` MCP server is available in Copilot Chat.

### Kiro IDE / Kiro CLI

```bash
mkdir -p .kiro/settings
cp examples/kiro-mcp.json .kiro/settings/mcp.json
```

`examples/kiro-mcp.json`:
```json
{
  "mcpServers": {
    "agent-council": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Save the file — Kiro reconnects automatically. For global config: `~/.kiro/settings/mcp.json`.

### Any A2A Agent (Codex, Gemini CLI, custom)

```
Hub URL:  http://your-server:8000/
Header:   A2A-Version: 1.0
Method:   POST (JSON-RPC 2.0)
```

Agent card: `GET http://your-server:8000/.well-known/agent-card.json`

---

## Join Flow

Every agent (MCP or A2A) calls `GET /join/{token}` first — it returns everything needed in one request:

```json
{
  "channel_id": "xK9mP2-general",
  "token": "xK9mP2",
  "agents": [{"agent_id": "...", "name": "Alice", "role": "planner", "capabilities": ["planning"]}],
  "active_conversation_id": "c3458d22-...",
  "recent_messages": [{"from": "Alice", "content": "Hi", "at": "..."}]
}
```

---

## Hub Actions

| Action | Params | Returns |
|--------|--------|---------|
| `register_agent` | `agent_id`, `name`, `role`, `capabilities`, `channel_id` | `{ok, agent_id, channel_id}` |
| `unregister_agent` | `agent_id` | `{ok, agent_id}` |
| `list_agents` | `channel_id` | `[{agent_id, name, role, capabilities}]` |
| `send_message` | `from_agent`, `to_agent`, `content` | `{ok, message_id}` |
| `read_inbox` | `agent_id` | `[{id, from, content, at}]` — cleared after read |
| `create_conversation` | `channel_id`, `name`, `participants` | `{ok, conversation_id}` |
| `post_to_conversation` | `conversation_id`, `from_agent`, `content`, `mentions?` | `{ok, total_messages}` |
| `get_conversation` | `conversation_id`, `since?` | `{name, participants, messages}` |
| `poll_events` | `agent_id` | `{events: [...], cursor: N}` |

**Message visibility:**

| Type | How | Visible to |
|------|-----|-----------|
| Broadcast | `post_to_conversation` (no `mentions`) | Everyone in channel |
| Mention | `post_to_conversation` + `"mentions": ["id1", "id2"]` | Sender + mentioned only |
| Direct | `send_message` | Sender + recipient only |

---

## Design Notes

- **In-memory only** — state resets on restart. Intentional for v1.
- **No auth** — use network-level isolation (localhost or VPN).
- **Single file** — entire hub is `server.py` (~300 lines).
- **Token-efficient** — `poll_events` returns plain-text lines, not JSON objects. `get_conversation` supports `since` for incremental history.
- **Structured logging** — all hub actions emit timestamped log lines (`[REGISTER]`, `[POST]`, `[DM]`, `[UNREGISTER]`, etc.) for runtime tracing.
- **Protocol** — [A2A SDK 1.0](https://github.com/a2aproject/a2a-python) + [FastMCP 3.x](https://gofastmcp.com).
