"""AgentCouncil: Universal Multi-Agent A2A Hub.

Agents register with a channel_id to scope their presence to a project.
All communication flows through this hub — never agent-to-agent directly.

Run:
    python server.py
    python server.py --host 0.0.0.0 --port 8000
"""

import random
import string
import uuid
from datetime import datetime, UTC

from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers.default_request_handler import LegacyRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types.a2a_pb2 import (
    AgentCard,
    AgentCapabilities,
    AgentInterface,
    AgentSkill,
    Part,
    TaskState,
)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_agents: dict[str, dict] = {}
# agent_id -> {name, capabilities, channel_id, registered_at}

_inboxes: dict[str, list] = {}
# agent_id -> [{id, from, content, at}]

_conversations: dict[str, dict] = {}
# conv_id -> {name, channel_id, participants, messages, created_at}

# ---------------------------------------------------------------------------
# Token + event store
# ---------------------------------------------------------------------------

TOKEN: str = "".join(random.choices(string.ascii_letters + string.digits, k=6))

_events: list[str] = []
# plain-text event log: "alice: message", "bob joined as reviewer", etc.

_cursors: dict[str, int] = {}
# agent_id -> last event index delivered via poll_events


def _emit(event: str) -> None:
    _events.append(event)


# ---------------------------------------------------------------------------
# FastMCP (MCP endpoint at /mcp)
# ---------------------------------------------------------------------------

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
def poll_events_mcp(agent_id: str) -> dict:
    """Retrieve new channel events since last poll. Returns compact plain-text lines.

    Call before every reply to get messages you may have missed.
    Mention events (sender->targets: content) are filtered — only visible to sender and mentioned agents.
    """
    return _dispatch({"action": "poll_events", "agent_id": agent_id})


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Action dispatcher
# ---------------------------------------------------------------------------

def _dispatch(data: dict) -> dict | list:
    action = data.get("action")
    match action:
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

        case "list_agents":
            channel_id = data["channel_id"]
            return [
                {"agent_id": aid, **info}
                for aid, info in _agents.items()
                if info["channel_id"] == channel_id
            ]

        case "send_message":
            to = data["to_agent"]
            if to not in _agents:
                return {"ok": False, "error": f"Unknown agent: {to}"}
            msg = {
                "id": str(uuid.uuid4()),
                "from": data["from_agent"],
                "content": data["content"],
                "at": _now(),
            }
            _inboxes[to].append(msg)
            return {"ok": True, "message_id": msg["id"]}

        case "read_inbox":
            agent_id = data["agent_id"]
            msgs = _inboxes.get(agent_id, [])
            _inboxes[agent_id] = []
            return msgs

        case "create_conversation":
            conv_id = str(uuid.uuid4())
            _conversations[conv_id] = {
                "name": data["name"],
                "channel_id": data["channel_id"],
                "participants": data.get("participants", []),
                "messages": [],
                "created_at": _now(),
            }
            return {"ok": True, "conversation_id": conv_id}

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

        case "get_conversation":
            conv = _conversations.get(data["conversation_id"])
            if not conv:
                return {"ok": False, "error": "Conversation not found"}
            since = data.get("since", 0)
            result = dict(conv)
            result["messages"] = conv["messages"][since:]
            return result

        case "poll_events":
            agent_id = data["agent_id"]
            cursor = _cursors.get(agent_id, 0)
            new_events = _events[cursor:]
            visible = []
            for event in new_events:
                if "→" in event.split(":")[0]:
                    header = event.split(":")[0]
                    sender, targets_str = header.split("→")
                    targets = targets_str.split(",")
                    if agent_id == sender or agent_id in targets:
                        visible.append(event)
                else:
                    visible.append(event)
            _cursors[agent_id] = cursor + len(new_events)
            return {"events": visible, "cursor": _cursors[agent_id]}

        case _:
            return {"ok": False, "error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# A2A executor
# ---------------------------------------------------------------------------

class HubExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        result: dict | list = {"ok": False, "error": "No data part in request"}
        if context.message:
            for part in context.message.parts:
                which = part.WhichOneof("content")
                if which == "data":
                    result = _dispatch(MessageToDict(part.data))
                    break
                elif which == "text" and part.text:
                    import json
                    try:
                        result = _dispatch(json.loads(part.text))
                    except Exception as e:
                        result = {"ok": False, "error": str(e)}
                    break

        value = ParseDict(result, Value())
        await updater.add_artifact(parts=[Part(data=value)], last_chunk=True)
        await updater.update_status(TaskState.TASK_STATE_COMPLETED)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

SKILLS = [
    ("register_agent", "Register Agent", "Announce presence in a channel"),
    ("list_agents", "List Agents", "Discover agents in a channel"),
    ("send_message", "Send Message", "Direct message to an agent's inbox"),
    ("read_inbox", "Read Inbox", "Retrieve and clear pending messages"),
    ("create_conversation", "Create Conversation", "Start a channel-scoped group discussion"),
    ("post_to_conversation", "Post to Conversation", "Contribute to a group discussion"),
    ("get_conversation", "Get Conversation", "Read full conversation history"),
]

AGENT_CARD = AgentCard(
    name="AgentCouncil",
    description=(
        "Universal multi-agent coordination hub. "
        "Register with a channel_id to scope your agent to a project. "
        "Send messages, create conversations, and collaborate."
    ),
    version="0.1.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[AgentInterface(url="http://127.0.0.1:8000/")],
    skills=[AgentSkill(id=sid, name=name, description=desc) for sid, name, desc in SKILLS],
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

async def _join_handler(request: Request) -> JSONResponse:
    token = request.path_params["token"]
    if token != TOKEN:
        return JSONResponse({"error": "Invalid token"}, status_code=404)
    channel_id = f"{TOKEN}-general"
    agents = [
        {
            "agent_id": aid,
            "name": info["name"],
            "role": info.get("role", ""),
            "capabilities": info["capabilities"],
        }
        for aid, info in _agents.items()
        if info["channel_id"] == channel_id
    ]
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


_handler = LegacyRequestHandler(
    agent_executor=HubExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=AGENT_CARD,
)

_mcp_app = _mcp.http_app(path="/")

app = Starlette(
    lifespan=_mcp_app.lifespan,
    routes=(
        create_agent_card_routes(AGENT_CARD)
        + create_jsonrpc_routes(_handler, rpc_url="/")
        + [
            Route("/join/{token}", _join_handler),
            Mount("/mcp", app=_mcp_app),
        ]
    )
)

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

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
