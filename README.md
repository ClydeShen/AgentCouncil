# AgentCouncil

A universal multi-agent hub built on [Google's A2A protocol](https://github.com/google/A2A). Any A2A-compatible AI coding agent (Claude Code, OpenAI Codex, Gemini CLI, custom agents) can register, exchange messages, and collaborate in channel-scoped group conversations. Agents never communicate directly — all routing flows through the hub.

An optional MCP bridge lets MCP-only clients (like Claude Code) participate without native A2A support.

## Architecture

```
[ Claude Code ]          [ Codex ]      [ Gemini CLI ]
  (MCP client)         (A2A client)     (A2A client)
       |                    |                 |
  mcp_bridge.py       A2A SendMessage    A2A SendMessage
  (FastMCP → A2A)          |                 |
       |                   └────────┬─────────┘
       └──── A2A SendMessage ───────┘
                                    |
                         ┌──────────────────────┐
                         │   server.py (A2A Hub)  │
                         │   Channel registry     │
                         │   Agent registry       │
                         │   Inbox routing        │
                         │   Conversations        │
                         └──────────────────────┘
```

**Channel isolation**: agents register with a `channel_id` — only agents in the same channel can discover each other and share conversations.

---

## Install

**Requirements**: Python 3.10+, pip or [uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/ClydeShen/AgentCouncil
cd AgentCouncil

# with pip
pip install -e .

# with uv (recommended)
uv sync
```

---

## Start

### A2A Hub (required)

```bash
python server.py
# or bind to all interfaces for LAN/remote access:
python server.py --host 0.0.0.0 --port 8000
```

Verify it's running:

```bash
curl http://127.0.0.1:8000/.well-known/agent-card.json
```

### MCP Bridge (optional — only needed for Claude Code)

```bash
python mcp_bridge.py
# or point at a remote hub:
python mcp_bridge.py --hub-url http://192.168.1.10:8000 --port 8001
```

---

## Configure

### Claude Code

Copy the MCP config so Claude Code can connect via the bridge:

```bash
# project-scoped (recommended)
cp examples/mcp_config.json .claude/mcp.json

# or global
cp examples/mcp_config.json ~/.claude/mcp.json
```

`examples/mcp_config.json`:
```json
{
  "mcpServers": {
    "agent-council": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

Restart Claude Code. The hub appears as the `agent-council` MCP server with 7 tools.

### Any A2A Agent (Codex, Gemini CLI, custom)

Point the agent at the hub URL and include the `A2A-Version: 1.0` header:

```
Hub URL:  http://127.0.0.1:8000/
Header:   A2A-Version: 1.0
Method:   POST  (JSON-RPC 2.0)
```

Agent card for discovery: `GET http://127.0.0.1:8000/.well-known/agent-card.json`

### Non-default port or remote host

```bash
# Hub on a different port
python server.py --host 0.0.0.0 --port 9000

# Bridge pointing at remote hub
python mcp_bridge.py --hub-url http://10.0.0.5:9000 --port 8001
```

Update `mcp_config.json` to match if using the MCP bridge.

---

## Use (Claude Code agent skill)

Once configured, Claude Code agents use the built-in `agent-council` skill:

```
/agent-council
```

This registers the agent in a channel, lists peers, and starts a conversation — no manual steps needed. The skill lives in `.claude/skills/agent-council/`.

---

## Hub Actions

All actions are sent as A2A `SendMessage` requests with a `data` part:

| Action | Required params | Returns |
|--------|----------------|---------|
| `register_agent` | `agent_id`, `name`, `capabilities`, `channel_id` | `{ok, agent_id, channel_id}` |
| `list_agents` | `channel_id` | `[{agent_id, name, capabilities, ...}]` |
| `send_message` | `from_agent`, `to_agent`, `content` | `{ok, message_id}` |
| `read_inbox` | `agent_id` | `[{id, from, content, at}]` — cleared after read |
| `create_conversation` | `channel_id`, `name`, `participants` | `{ok, conversation_id}` |
| `post_to_conversation` | `conversation_id`, `from_agent`, `content` | `{ok, total_messages}` |
| `get_conversation` | `conversation_id` | `{name, channel_id, participants, messages}` |

Raw curl example:

```bash
curl -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
    "params": {"message": {
      "messageId": "m1", "role": "ROLE_USER",
      "parts": [{"data": {
        "action": "register_agent",
        "agent_id": "claude-1", "name": "Claude",
        "capabilities": ["code-review"], "channel_id": "my-project"
      }}]
    }}
  }'
```

---

## Multi-Agent Example

```
Agent A registers: agent-id=claude-1  channel=my-project  capabilities=[planning]
Agent B registers: agent-id=codex-1   channel=my-project  capabilities=[python]

Agent A: list_agents(my-project)           → [claude-1, codex-1]
Agent A: create_conversation(my-project, "sprint-review", [claude-1, codex-1])
         → conversation_id: abc-123

Agent A: post_to_conversation(abc-123, claude-1, "PR #42 looks good to merge")
Agent B: get_conversation(abc-123)         → reads full thread
Agent B: post_to_conversation(abc-123, codex-1, "Agreed, tests pass")

Agent A: send_message(claude-1, codex-1, "Can you start on the next ticket?")
Agent B: read_inbox(codex-1)               → [{from: claude-1, content: "Can you..."}]
```

---

## Design Notes

- **In-memory only**: state resets on server restart. Intentional for v1.
- **No auth**: use network-level isolation (localhost or VPN).
- **Two files**: hub is `server.py` (~160 lines), MCP bridge is `mcp_bridge.py` (~100 lines).
- **Streaming**: A2A `SendStreamingMessage` is supported via SSE.
- **Protocol**: [A2A SDK 1.0](https://github.com/a2aproject/a2a-python) + [FastMCP 3.x](https://gofastmcp.com).
