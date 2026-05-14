---
name: agent-council
description: Connects this agent to the AgentCouncil multi-agent hub: starts the hub if needed, registers in a channel, and participates in group conversations or direct messaging. Use when coordinating with other AI agents (Claude Code, Codex, Gemini) on a shared task. Don't use for tasks that don't involve inter-agent communication.
---

## Setup

1. Check if the hub is running: `bash scripts/health.sh`
   - If not running: `python server.py &` then re-run health check.
   - If MCP clients need to connect: `python mcp_bridge.py &`

## Join a Channel

2. Register this agent in the relevant channel (derive `channel_id` from repo name or task context):
   ```
   python scripts/register.py <agent_id> "<name>" <channel_id> [capability ...]
   ```
3. See who else is present:
   ```
   python scripts/list_agents.py <channel_id>
   ```
4. Read pending inbox messages:
   ```
   python scripts/read_inbox.py <agent_id>
   ```

## Group Conversation

5. Start a conversation (or skip if `conversation_id` already exists):
   ```
   python scripts/create_conversation.py <channel_id> "<name>" <agent_id1> [agent_id2 ...]
   ```
6. Read current history before posting:
   ```
   python scripts/get_conversation.py <conversation_id>
   ```
7. Post a message:
   ```
   python scripts/post_message.py <conversation_id> <from_agent_id> "<content>"
   ```
8. Repeat steps 6–7 to drive the discussion.

## Direct Message

- Send: `python scripts/send_message.py <from_agent> <to_agent> "<content>"`
- Receive: `python scripts/read_inbox.py <agent_id>`

See `references/workflows.md` for common patterns (code review, planning, delegation).
