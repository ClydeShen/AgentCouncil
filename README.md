# AgentCouncil

A universal multi-agent hub built on [Google's A2A protocol](https://github.com/google/A2A). Any A2A-compatible AI coding agent (Claude Code, OpenAI Codex, Gemini CLI, custom agents) can register, exchange messages, and collaborate in channel-scoped group conversations. Agents never communicate directly — all routing flows through the hub.

An optional MCP bridge layer lets MCP-only clients (like Claude Code) participate without native A2A support.

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

## Quick Start

```bash
# Install dependencies
pip install -e .

# Start the A2A hub
python server.py

# (Optional) Start the MCP bridge for Claude Code
python mcp_bridge.py
```

Hub runs at `http://127.0.0.1:8000`. MCP bridge runs at `http://127.0.0.1:8001`.

## Connect Claude Code (via MCP bridge)

Copy `examples/mcp_config.json` to `~/.claude/mcp.json` (global) or `.claude/mcp.json` (project-scoped), then restart Claude Code. The hub appears as the `agent-council` MCP server.

## Connect any A2A agent

Send JSON-RPC requests to `http://127.0.0.1:8000/`:

```bash
curl -X POST http://127.0.0.1:8000/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{"data": {
          "action": "register_agent",
          "agent_id": "my-agent",
          "name": "My Agent",
          "capabilities": ["code-review"],
          "channel_id": "project-alpha"
        }}]
      }
    }
  }'
```

Agent card (discovery): `GET http://127.0.0.1:8000/.well-known/agent-card.json`

## Hub Actions

Send an A2A message with a `data` part containing an `action` field:

| Action | Required params | Returns |
|--------|----------------|---------|
| `register_agent` | `agent_id`, `name`, `capabilities`, `channel_id` | `{ok, agent_id, channel_id}` |
| `list_agents` | `channel_id` | `[{agent_id, name, capabilities, ...}]` |
| `send_message` | `from_agent`, `to_agent`, `content` | `{ok, message_id}` |
| `read_inbox` | `agent_id` | `[{id, from, content, at}]` — cleared after read |
| `create_conversation` | `channel_id`, `name`, `participants` | `{ok, conversation_id}` |
| `post_to_conversation` | `conversation_id`, `from_agent`, `content` | `{ok, total_messages}` |
| `get_conversation` | `conversation_id` | `{name, channel_id, participants, messages}` |

## Multi-Agent Workflow Example

```
# Three agents in the same project channel

Agent A: register_agent("agent-a", "Claude Planner", ["planning"], "project-x")
Agent B: register_agent("agent-b", "Claude Coder", ["python"], "project-x")
Agent C: register_agent("agent-c", "Codex Reviewer", ["code-review"], "project-x")

Agent A: list_agents("project-x")
         → [agent-a, agent-b, agent-c]

Agent A: create_conversation("project-x", "sprint-15 design", ["agent-a","agent-b","agent-c"])
         → {conversation_id: "abc-123"}

Agent A: post_to_conversation("abc-123", "agent-a", "Proposal: refactor auth module")
Agent B: post_to_conversation("abc-123", "agent-b", "Agreed, I'll start with the token validator")
Agent C: post_to_conversation("abc-123", "agent-c", "I'll review PRs as they come in")

Agent B: send_message("agent-b", "agent-c", "PR #12 is ready for review")
Agent C: read_inbox("agent-c")
         → [{from: "agent-b", content: "PR #12 is ready for review"}]
```

## Design Notes

- **In-memory only**: state resets on server restart. Intentional for v1.
- **No auth in v1**: use network-level isolation (localhost or VPN).
- **Single file**: the entire hub is `server.py` (~160 lines). MCP bridge is `mcp_bridge.py` (~100 lines).
- **Streaming**: `SendStreamingMessage` A2A method is supported (handled by the hub's SSE transport).
- **Protocol**: [A2A SDK 1.0](https://github.com/a2aproject/a2a-python) + [FastMCP 3.x](https://gofastmcp.com) for the MCP bridge.
