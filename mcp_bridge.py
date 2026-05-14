"""AgentCouncil MCP Bridge — optional middleware layer.

Translates MCP tool calls into A2A messages sent to the AgentCouncil hub.
Run this alongside server.py so MCP-only clients (e.g. Claude Code) can
participate in the hub without native A2A support.

Run:
    python mcp_bridge.py
    python mcp_bridge.py --hub-url http://192.168.1.10:8000 --port 8001
"""

import json
import uuid

import httpx
from fastmcp import FastMCP

mcp = FastMCP(
    name="AgentCouncil MCP Bridge",
    instructions=(
        "MCP adapter for the AgentCouncil A2A hub. "
        "Use these tools to register, discover agents, exchange messages, "
        "and collaborate in channel-scoped conversations."
    ),
)

HUB_URL = "http://127.0.0.1:8000"


def _call(action: str, **kwargs) -> dict | list:
    """Send an action to the A2A hub and return the result artifact."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {"action": action, **kwargs}}],
            }
        },
    }
    resp = httpx.post(HUB_URL, json=payload, headers={"A2A-Version": "1.0"}, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    artifacts = body.get("result", {}).get("task", {}).get("artifacts", [])
    if artifacts:
        parts = artifacts[0].get("parts", [])
        if parts:
            return parts[0].get("data", {"ok": False, "error": "No data in part"})
    return {"ok": False, "error": "No artifacts in response", "raw": body}


# ---------------------------------------------------------------------------
# MCP tools — mirror the hub's 7 actions
# ---------------------------------------------------------------------------

@mcp.tool
def register_agent(agent_id: str, name: str, capabilities: list[str], channel_id: str) -> dict:
    """Register this agent in a channel.

    channel_id scopes the agent to a project workspace (e.g. 'my-repo', 'sprint-12').
    Call once at session start. Re-calling updates the registration.
    """
    return _call("register_agent", agent_id=agent_id, name=name,
                 capabilities=capabilities, channel_id=channel_id)


@mcp.tool
def list_agents(channel_id: str) -> list:
    """List all agents registered in the given channel."""
    return _call("list_agents", channel_id=channel_id)


@mcp.tool
def send_message(from_agent: str, to_agent: str, content: str) -> dict:
    """Send a direct message to another agent's inbox.

    The recipient retrieves it via read_inbox(). Messages queue until read.
    """
    return _call("send_message", from_agent=from_agent, to_agent=to_agent, content=content)


@mcp.tool
def read_inbox(agent_id: str) -> list:
    """Retrieve and clear all pending direct messages for this agent."""
    return _call("read_inbox", agent_id=agent_id)


@mcp.tool
def create_conversation(channel_id: str, name: str, participants: list[str]) -> dict:
    """Start a named group conversation scoped to a channel.

    Returns a conversation_id. Any agent can post to it via post_to_conversation().
    """
    return _call("create_conversation", channel_id=channel_id, name=name,
                 participants=participants)


@mcp.tool
def post_to_conversation(conversation_id: str, from_agent: str, content: str) -> dict:
    """Append a message to a group conversation.

    Read the current history first via get_conversation() to maintain context.
    """
    return _call("post_to_conversation", conversation_id=conversation_id,
                 from_agent=from_agent, content=content)


@mcp.tool
def get_conversation(conversation_id: str) -> dict:
    """Read the full message history and metadata for a conversation."""
    return _call("get_conversation", conversation_id=conversation_id)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AgentCouncil MCP Bridge")
    parser.add_argument("--hub-url", default="http://127.0.0.1:8000",
                        help="URL of the AgentCouncil A2A hub")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8001, help="Bind port")
    args = parser.parse_args()

    HUB_URL = args.hub_url
    print(f"MCP bridge connecting to hub at {HUB_URL}")
    print(f"MCP endpoint: http://{args.host}:{args.port}/mcp")
    mcp.run(transport="streamable-http", host=args.host, port=args.port)
