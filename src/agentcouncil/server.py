"""AgentCouncil: Universal Multi-Agent A2A Hub.

Agents register with a channel_id to scope their presence to a project.
All communication flows through this hub — never agent-to-agent directly.

Run:
    python server.py
    python server.py --host 0.0.0.0 --port 8000
"""

import logging
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
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agentcouncil")

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

_disabled: set[str] = set()
_recent_sends: dict[tuple, float] = {}
# (from_agent, target, content) → timestamp; used to deduplicate repeated sends within 10s
_DEDUP_TTL: float = 10.0
_agent_colors: dict[str, str] = {}
_COLORS: list[str] = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#e91e63",
]
_dash_queues: list = []


def _emit(event: str) -> None:
    _events.append(event)
    log.info("[EVENT] %s", event)


def _dash_emit(event_type: str, payload: dict) -> None:
    import json
    import asyncio
    data = json.dumps({"type": event_type, **payload})
    for q in list(_dash_queues):
        try:
            asyncio.get_event_loop().call_soon_threadsafe(q.put_nowait, data)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FastMCP (MCP endpoint at /mcp)
# ---------------------------------------------------------------------------

from fastmcp import FastMCP as _FastMCP

_mcp = _FastMCP(
    name="AgentCouncil",
    instructions=(
        "Tools for the AgentCouncil multi-agent hub. "
        "Start with join_channel to get context, then register_agent to announce yourself. "
        "Call poll_events before every reply to receive new messages. "
        "Use post_to_conversation to send messages to the group."
    ),
)


@_mcp.tool
def join_channel(token: str) -> dict:
    """Get full channel context from a join link token (the part after /join/).

    Returns channel_id, active_conversation_id, current agents, and recent messages.
    Call this once at session start before registering.
    """
    channel_id = f"{TOKEN}-general"
    if token != TOKEN:
        return {"ok": False, "error": "Invalid token"}
    agents = [
        {"agent_id": aid, "name": info["name"], "role": info.get("role", ""), "capabilities": info["capabilities"]}
        for aid, info in _agents.items()
        if info["channel_id"] == channel_id
    ]
    active_conv_id = None
    recent_messages = []
    for conv_id, conv in _conversations.items():
        if conv["channel_id"] == channel_id:
            active_conv_id = conv_id
            recent_messages = conv["messages"][-10:]
    return {"channel_id": channel_id, "token": TOKEN, "agents": agents,
            "active_conversation_id": active_conv_id, "recent_messages": recent_messages}


@_mcp.tool
def register_agent(agent_id: str, name: str, channel_id: str, role: str = "", capabilities: list[str] = []) -> dict:
    """Register this agent in a channel. Call once at session start after join_channel.

    role: planner | implementer | reviewer | researcher (optional)
    agent_id: unique ID, e.g. "kiro-abc1" — use hostname + random suffix
    """
    return _dispatch({"action": "register_agent", "agent_id": agent_id, "name": name,
                      "channel_id": channel_id, "role": role, "capabilities": capabilities})


@_mcp.tool
def list_agents(channel_id: str) -> list:
    """List all agents currently registered in a channel."""
    return _dispatch({"action": "list_agents", "channel_id": channel_id})


@_mcp.tool
def create_conversation(channel_id: str, name: str, participants: list[str]) -> dict:
    """Create a new group conversation in a channel. Returns conversation_id."""
    return _dispatch({"action": "create_conversation", "channel_id": channel_id,
                      "name": name, "participants": participants})


@_mcp.tool
def post_to_conversation(conversation_id: str, from_agent: str, content: str, mentions: list[str] = []) -> dict:
    """Post a message to a group conversation.

    mentions: list of agent_ids to notify privately (optional — omit for broadcast).
    Call poll_events first to read any new messages before replying.
    """
    return _dispatch({"action": "post_to_conversation", "conversation_id": conversation_id,
                      "from_agent": from_agent, "content": content, "mentions": mentions})


@_mcp.tool
def get_conversation(conversation_id: str, since: int = 0) -> dict:
    """Read conversation history. Use since=N to fetch only messages after index N."""
    return _dispatch({"action": "get_conversation", "conversation_id": conversation_id, "since": since})


@_mcp.tool
def send_direct_message(from_agent: str, to_agent: str, content: str) -> dict:
    """Send a private direct message to another agent's inbox."""
    return _dispatch({"action": "send_message", "from_agent": from_agent,
                      "to_agent": to_agent, "content": content})


@_mcp.tool
def read_inbox(agent_id: str) -> list:
    """Read and clear all pending direct messages for this agent."""
    return _dispatch({"action": "read_inbox", "agent_id": agent_id})


@_mcp.tool
def poll_events(agent_id: str) -> dict:
    """Retrieve new channel events since last poll. Call before every reply.

    Returns compact plain-text lines. Mention events are filtered —
    only visible to sender and mentioned agents.
    """
    return _dispatch({"action": "poll_events", "agent_id": agent_id})


@_mcp.tool
def unregister_agent(agent_id: str) -> dict:
    """Leave the channel and clean up this agent's presence.

    Removes the agent from the registry, clears their inbox, and emits
    a departure event to all channel members. Call this before ending a session.
    """
    return _dispatch({"action": "unregister_agent", "agent_id": agent_id})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check_dedup(from_agent: str, target: str, content: str) -> bool:
    """Return True if this (from, target, content) was already sent within _DEDUP_TTL seconds."""
    import time
    key = (from_agent, target, content)
    now = time.monotonic()
    # expire old entries
    expired = [k for k, ts in _recent_sends.items() if now - ts > _DEDUP_TTL]
    for k in expired:
        del _recent_sends[k]
    if key in _recent_sends:
        return True
    _recent_sends[key] = now
    return False


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
            _agent_colors[agent_id] = _COLORS[len(_agent_colors) % len(_COLORS)]
            role_str = f" as {role}" if role else ""
            _emit(f"{data['name']} joined{role_str}")
            _dash_emit("agent_joined", {
                "id": agent_id,
                "name": data["name"],
                "role": role,
                "color": _agent_colors[agent_id],
            })
            log.info("[REGISTER] agent_id=%s name=%r role=%r channel=%s",
                     agent_id, data["name"], role, data["channel_id"])
            return {"ok": True, "agent_id": agent_id, "channel_id": data["channel_id"]}

        case "list_agents":
            channel_id = data["channel_id"]
            return [
                {"agent_id": aid, **info}
                for aid, info in _agents.items()
                if info["channel_id"] == channel_id
            ]

        case "send_message":
            if data["from_agent"] in _disabled:
                return {"ok": False, "error": "agent disabled"}
            if _check_dedup(data["from_agent"], data["to_agent"], data["content"]):
                return {"ok": False, "error": "duplicate message — same content sent within 10s"}
            to = data["to_agent"]
            if to not in _agents:
                log.warning("[DM] unknown recipient agent_id=%s from=%s", to, data["from_agent"])
                return {"ok": False, "error": f"Unknown agent: {to}"}
            msg = {
                "id": str(uuid.uuid4()),
                "from": data["from_agent"],
                "content": data["content"],
                "at": _now(),
            }
            _inboxes[to].append(msg)
            _dash_emit("message", {
                "from": data["from_agent"],
                "from_id": data["from_agent"],
                "to": to,
                "content": data["content"],
                "at": msg["at"],
                "color": _agent_colors.get(data["from_agent"], _COLORS[0]),
            })
            log.info("[DM] from=%s to=%s msg_id=%s content=%r",
                     data["from_agent"], to, msg["id"], data["content"][:120])
            return {"ok": True, "message_id": msg["id"]}

        case "read_inbox":
            agent_id = data["agent_id"]
            if agent_id in _disabled:
                _inboxes[agent_id] = []
                return []
            msgs = _inboxes.get(agent_id, [])
            _inboxes[agent_id] = []
            log.info("[INBOX] agent_id=%s cleared %d message(s)", agent_id, len(msgs))
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
            log.info("[CONV] created conv_id=%s name=%r channel=%s participants=%s",
                     conv_id, data["name"], data["channel_id"], data.get("participants", []))
            return {"ok": True, "conversation_id": conv_id}

        case "post_to_conversation":
            if data["from_agent"] in _disabled:
                return {"ok": False, "error": "agent disabled"}
            if _check_dedup(data["from_agent"], data["conversation_id"], data["content"]):
                return {"ok": False, "error": "duplicate message — same content sent within 10s"}
            conv = _conversations.get(data["conversation_id"])
            if not conv:
                log.warning("[POST] conversation not found conv_id=%s from=%s",
                            data["conversation_id"], data["from_agent"])
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
                log.info("[POST] conv_id=%s from=%s mentions=%s content=%r",
                         data["conversation_id"], data["from_agent"], mentions, data["content"][:120])
            else:
                _emit(f"{agent_name}: {data['content']}")
                log.info("[POST] conv_id=%s from=%s (broadcast) content=%r",
                         data["conversation_id"], data["from_agent"], data["content"][:120])
            _dash_emit("message", {
                "from": agent_name,
                "from_id": data["from_agent"],
                "to": ",".join(mentions) if mentions else "all",
                "content": data["content"],
                "at": conv["messages"][-1]["at"],
                "color": _agent_colors.get(data["from_agent"], _COLORS[0]),
            })
            return {"ok": True, "total_messages": len(conv["messages"])}

        case "get_conversation":
            conv = _conversations.get(data["conversation_id"])
            if not conv:
                log.warning("[GET_CONV] not found conv_id=%s", data["conversation_id"])
                return {"ok": False, "error": "Conversation not found"}
            since = data.get("since", 0)
            result = dict(conv)
            result["messages"] = conv["messages"][since:]
            log.info("[GET_CONV] conv_id=%s since=%d returning %d message(s)",
                     data["conversation_id"], since, len(result["messages"]))
            return result

        case "poll_events":
            agent_id = data["agent_id"]
            if agent_id in _disabled:
                return {"events": [], "cursor": _cursors.get(agent_id, 0)}
            cursor = _cursors.get(agent_id, 0)
            new_events = _events[cursor:]
            agent_name = _agents.get(agent_id, {}).get("name", "")
            visible = []
            for event in new_events:
                if "→" in event.split(":")[0]:
                    header = event.split(":")[0]
                    sender, targets_str = header.split("→")
                    targets = targets_str.split(",")
                    # only deliver to recipients, not the sender
                    if agent_id in targets:
                        visible.append(event)
                else:
                    # broadcast: skip events sent by this agent
                    if agent_name and event.startswith(f"{agent_name}: "):
                        continue
                    visible.append(event)
            _cursors[agent_id] = cursor + len(new_events)
            return {"events": visible, "cursor": _cursors[agent_id]}

        case "unregister_agent":
            agent_id = data["agent_id"]
            if agent_id not in _agents:
                log.warning("[UNREGISTER] unknown agent_id=%s", agent_id)
                return {"ok": False, "error": f"Unknown agent: {agent_id}"}
            agent_name = _agents[agent_id]["name"]
            channel_id = _agents[agent_id]["channel_id"]
            del _agents[agent_id]
            _inboxes.pop(agent_id, None)
            _cursors.pop(agent_id, None)
            _agent_colors.pop(agent_id, None)
            _disabled.discard(agent_id)
            for k in [k for k in _recent_sends if k[0] == agent_id]:
                del _recent_sends[k]
            _emit(f"{agent_name} left")
            _dash_emit("agent_left", {"id": agent_id})
            log.info("[UNREGISTER] agent_id=%s name=%r channel=%s", agent_id, agent_name, channel_id)
            return {"ok": True, "agent_id": agent_id}

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
    ("unregister_agent", "Unregister Agent", "Leave a channel and clean up agent presence"),
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
    version="0.4.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[AgentInterface(url="http://127.0.0.1:8000/")],
    skills=[AgentSkill(id=sid, name=name, description=desc) for sid, name, desc in SKILLS],
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

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


async def _dashboard_events(request: Request):
    import asyncio
    import json
    from starlette.responses import StreamingResponse

    queue: asyncio.Queue = asyncio.Queue()
    _dash_queues.append(queue)

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
    _seen = set()
    for conv in _conversations.values():
        if conv["channel_id"] == channel_id:
            for m in conv["messages"][-50:]:
                from_id = m["from"]
                dedup_key = (from_id, m["content"])
                if dedup_key in _seen:
                    continue
                _seen.add(dedup_key)
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
            yield 'data: {"type":"ping"}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            try:
                _dash_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentCouncil</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Sora:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
  tailwind.config = {
    theme: {
      extend: {
        fontFamily: {
          sans: ['Sora', 'ui-sans-serif'],
          mono: ['JetBrains Mono', 'ui-monospace'],
        },
        colors: {
          zinc: {
            950: '#09090b', 925: '#0f0f12', 900: '#18181b',
            800: '#27272a', 700: '#3f3f46', 600: '#52525b',
            500: '#71717a', 400: '#a1a1aa', 300: '#d4d4d8',
            200: '#e4e4e7', 100: '#f4f4f5', 50: '#fafafa',
          },
        },
        keyframes: {
          'fade-in': { from: { opacity: 0, transform: 'translateY(4px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
          'pulse-dot': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.35 } },
        },
        animation: {
          'fade-in': 'fade-in 0.2s ease-out',
          'pulse-dot': 'pulse-dot 2s ease-in-out infinite',
        },
      }
    }
  }
</script>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  :root {
    --bg:      #09090b;
    --surface: #18181b;
    --border:  #27272a;
    --muted:   #3f3f46;
    --text:    #fafafa;
    --text-2:  #a1a1aa;
    --text-3:  #71717a;
    --cyan:    #22d3ee;
    --cyan-dim:#164e63;
    --green:   #4ade80;
    --red:     #f87171;
    --amber:   #fbbf24;
  }

  html, body { height: 100%; overflow: hidden; }
  body { background: var(--bg); color: var(--text); font-family: 'Sora', ui-sans-serif; font-size: 13px; line-height: 1.5; }

  /* scrollbars */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 9999px; }

  /* focus rings — WCAG AA */
  :focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; border-radius: 4px; }

  /* shadcn-style btn base */
  .btn { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: 500; font-family: 'Sora', ui-sans-serif; cursor: pointer; transition: background 0.15s, color 0.15s, border-color 0.15s; border: 1px solid transparent; white-space: nowrap; }
  .btn:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
  .btn-ghost  { background: transparent; border-color: var(--border); color: var(--text-2); }
  .btn-ghost:hover  { background: var(--muted); color: var(--text); border-color: var(--muted); }
  .btn-danger { background: transparent; border-color: #7f1d1d; color: var(--red); }
  .btn-danger:hover { background: #450a0a; }
  .btn-success { background: transparent; border-color: #14532d; color: var(--green); }
  .btn-success:hover { background: #052e16; }

  /* role badge */
  .role-badge { display: inline-block; padding: 1px 7px; border-radius: 9999px; font-size: 10px; font-weight: 500; letter-spacing: 0.02em; font-family: 'JetBrains Mono', ui-monospace; }
  .role-planner     { background: #1e3a5f; color: #7dd3fc; border: 1px solid #1d4ed8; }
  .role-implementer { background: #14532d; color: #86efac; border: 1px solid #15803d; }
  .role-reviewer    { background: #3b1f6a; color: #c4b5fd; border: 1px solid #7c3aed; }
  .role-researcher  { background: #78350f; color: #fcd34d; border: 1px solid #d97706; }
  .role-default     { background: var(--muted); color: var(--text-3); border: 1px solid var(--border); }

  /* markdown render area */
  .md { font-size: 12px; line-height: 1.65; color: var(--text-2); }
  .md p    { margin: 0.2em 0; }
  .md p:first-child { margin-top: 0; }
  .md p:last-child  { margin-bottom: 0; }
  .md strong { color: var(--text); font-weight: 600; }
  .md em     { color: var(--text-2); }
  .md code   { font-family: 'JetBrains Mono', ui-monospace; font-size: 11px; background: #0d1117; color: #e2e8f0; padding: 1px 5px; border-radius: 4px; border: 1px solid var(--border); }
  .md pre    { background: #0d1117; border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; overflow-x: auto; margin: 6px 0; }
  .md pre code { background: none; border: none; padding: 0; font-size: 11px; color: #e2e8f0; }
  .md ul, .md ol { padding-left: 1.4em; margin: 4px 0; }
  .md li { margin: 2px 0; }
  .md h1 { font-size: 14px; font-weight: 600; color: var(--text); margin: 8px 0 4px; }
  .md h2 { font-size: 13px; font-weight: 600; color: var(--text); margin: 6px 0 3px; }
  .md h3 { font-size: 12px; font-weight: 600; color: var(--cyan); margin: 4px 0 2px; }
  .md blockquote { border-left: 2px solid var(--muted); padding-left: 10px; color: var(--text-3); margin: 4px 0; }
  .md a  { color: var(--cyan); text-decoration: underline; text-underline-offset: 2px; }
  .md hr { border: none; border-top: 1px solid var(--border); margin: 8px 0; }
  .md table { width: 100%; border-collapse: collapse; font-size: 11px; margin: 6px 0; }
  .md th { text-align: left; padding: 3px 8px; background: var(--surface); color: var(--text-3); font-weight: 500; border-bottom: 1px solid var(--border); }
  .md td { padding: 3px 8px; border-bottom: 1px solid var(--muted); }

  /* message fade-in */
  .msg-row { animation: fade-in 0.18s ease-out; }
  #messages-list { scroll-behavior: smooth; }

  /* status dot */
  .status-dot { width: 7px; height: 7px; border-radius: 9999px; display: inline-block; flex-shrink: 0; }
  .status-dot.live { background: var(--green); animation: pulse-dot 2s ease-in-out infinite; }
  .status-dot.dead { background: var(--red); }
  .status-dot.connecting { background: var(--amber); animation: pulse-dot 1.2s ease-in-out infinite; }

  /* agent card */
  .agent-card { border-bottom: 1px solid var(--border); padding: 10px 12px; cursor: pointer; transition: background 0.12s; }
  .agent-card:hover { background: #1c1c1f; }
  .agent-card:last-child { border-bottom: none; }
  .agent-card.is-disabled { opacity: 0.45; }

  /* panel header */
  .panel-hdr { padding: 8px 12px; font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); border-bottom: 1px solid var(--border); flex-shrink: 0; font-family: 'JetBrains Mono', ui-monospace; }

  /* dialog */
  .dialog { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; min-width: 320px; max-width: 480px; width: 90vw; box-shadow: 0 25px 60px rgba(0,0,0,0.7); }
  .dialog-row { display: flex; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
  .dialog-row:last-child { border-bottom: none; }
  .dialog-label { color: var(--text-3); width: 88px; flex-shrink: 0; font-family: 'JetBrains Mono', ui-monospace; font-size: 11px; padding-top: 1px; }
  .dialog-val { color: var(--text-2); word-break: break-all; }
</style>
</head>
<body>

<!-- ── APP SHELL ── -->
<div style="display:flex; flex-direction:column; height:100vh; overflow:hidden;">

  <!-- Header -->
  <header style="display:flex; align-items:center; gap:12px; padding:0 16px; height:48px; background:var(--surface); border-bottom:1px solid var(--border); flex-shrink:0;">
    <div style="display:flex; align-items:center; gap:8px;">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="9" stroke="#22d3ee" stroke-width="1.5"/>
        <circle cx="10" cy="10" r="4" fill="#22d3ee" opacity="0.25"/>
        <circle cx="10" cy="10" r="1.5" fill="#22d3ee"/>
        <line x1="10" y1="1" x2="10" y2="6" stroke="#22d3ee" stroke-width="1.2" opacity="0.5"/>
        <line x1="10" y1="14" x2="10" y2="19" stroke="#22d3ee" stroke-width="1.2" opacity="0.5"/>
        <line x1="1" y1="10" x2="6" y2="10" stroke="#22d3ee" stroke-width="1.2" opacity="0.5"/>
        <line x1="14" y1="10" x2="19" y2="10" stroke="#22d3ee" stroke-width="1.2" opacity="0.5"/>
      </svg>
      <span style="font-weight:600; font-size:13px; letter-spacing:-0.01em; color:#fafafa;">AgentCouncil</span>
    </div>

    <div id="status-wrap" style="display:flex; align-items:center; gap:6px; margin-left:4px;">
      <span id="status-dot" class="status-dot connecting" aria-hidden="true"></span>
      <span id="status" style="font-size:11px; color:var(--text-3); font-family:'JetBrains Mono',ui-monospace;" aria-live="polite">connecting…</span>
    </div>

    <button id="channel-chip"
      onclick="copyJoinUrl()"
      aria-label="Copy join URL to clipboard"
      title="Click to copy join URL"
      style="display:none; margin-left:auto; align-items:center; gap:6px; padding:4px 10px; background:var(--bg); border:1px solid var(--border); border-radius:6px; color:var(--text-3); font-size:11px; cursor:pointer; font-family:'JetBrains Mono',ui-monospace; transition:border-color 0.15s, color 0.15s;"
      onmouseover="this.style.borderColor='var(--cyan)';this.style.color='var(--cyan)';"
      onmouseout="this.style.borderColor='var(--border)';this.style.color='var(--text-3)';">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <rect x="4" y="4" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.2"/>
        <path d="M8 4V2.5A1.5 1.5 0 006.5 1h-4A1.5 1.5 0 001 2.5v4A1.5 1.5 0 002.5 8H4" stroke="currentColor" stroke-width="1.2"/>
      </svg>
      <span id="chip-text"></span>
    </button>
  </header>

  <!-- Body -->
  <div style="display:flex; flex:1; overflow:hidden;">

    <!-- Agents sidebar -->
    <aside style="width:212px; border-right:1px solid var(--border); display:flex; flex-direction:column; flex-shrink:0;" aria-label="Connected agents">
      <div class="panel-hdr" style="display:flex; justify-content:space-between; align-items:center;">
        <span>Agents</span>
        <span id="agent-count" style="color:var(--text-3); font-size:10px;"></span>
      </div>
      <div id="agents-list" style="flex:1; overflow-y:auto;" role="list"></div>
    </aside>

    <!-- Messages -->
    <main style="flex:1; display:flex; flex-direction:column; overflow:hidden;" aria-label="Message feed">
      <div class="panel-hdr">Messages</div>
      <div id="messages-list" style="flex:1; overflow-y:auto; padding:12px 16px; display:flex; flex-direction:column; gap:10px;" role="log" aria-live="polite" aria-atomic="false"></div>
    </main>

  </div>
</div>

<!-- Agent detail dialog -->
<div id="popup-overlay"
  role="dialog" aria-modal="true" aria-labelledby="popup-name"
  style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:50; align-items:center; justify-content:center; backdrop-filter:blur(2px);">
  <div class="dialog">
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:16px;">
      <span id="popup-dot" class="w-2.5 h-2.5 rounded-full" style="width:10px;height:10px;border-radius:9999px;flex-shrink:0;"></span>
      <h2 id="popup-name" style="font-size:14px; font-weight:600; color:var(--text); margin:0;"></h2>
      <span id="popup-role-badge" style="margin-left:4px;"></span>
    </div>
    <div id="popup-rows" style="margin-bottom:16px;"></div>
    <div style="display:flex; gap:8px; justify-content:flex-end; align-items:center;">
      <button onclick="closePopup()" class="btn btn-ghost">Close</button>
      <button id="popup-toggle-btn" class="btn"></button>
      <button id="popup-kick-btn" class="btn btn-danger">Kick</button>
    </div>
  </div>
</div>

<script>
  let agents = {};

  /* ── helpers ── */
  function ts(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); }
    catch { return iso.slice(11,16); }
  }

  function roleBadge(role) {
    const map = { planner:'role-planner', implementer:'role-implementer', reviewer:'role-reviewer', researcher:'role-researcher' };
    const cls = map[(role||'').toLowerCase()] || 'role-default';
    return role ? `<span class="role-badge ${cls}">${role}</span>` : `<span class="role-badge role-default">no role</span>`;
  }

  /* ── join URL chip ── */
  function copyJoinUrl() {
    const url = document.getElementById('chip-text').textContent;
    navigator.clipboard.writeText(url).then(() => {
      const chip = document.getElementById('channel-chip');
      const t = document.getElementById('chip-text');
      const prev = t.textContent;
      t.textContent = 'copied!';
      chip.style.borderColor = 'var(--green)';
      chip.style.color = 'var(--green)';
      setTimeout(() => {
        t.textContent = prev;
        chip.style.borderColor = 'var(--border)';
        chip.style.color = 'var(--text-3)';
      }, 1500);
    });
  }

  /* ── agent list ── */
  function renderAgents() {
    const list = document.getElementById('agents-list');
    list.innerHTML = '';
    const arr = Object.values(agents);
    const live = arr.filter(a => !a.disabled).length;
    document.getElementById('agent-count').textContent = live + ' live';

    arr.forEach(a => {
      const card = document.createElement('div');
      card.className = 'agent-card' + (a.disabled ? ' is-disabled' : '');
      card.setAttribute('role', 'listitem');
      card.innerHTML = `
        <div style="display:flex; align-items:center; gap:7px; margin-bottom:5px;">
          <span style="width:8px;height:8px;border-radius:9999px;flex-shrink:0;background:${a.color};${a.disabled ? '' : 'box-shadow:0 0 6px ' + a.color + '80;'}"></span>
          <button onclick="showPopup('${a.id}')" style="font-weight:600; font-size:12px; color:var(--text); background:none; border:none; cursor:pointer; padding:0; text-align:left;" aria-haspopup="dialog">${a.name}</button>
        </div>
        <div style="margin-bottom:7px; padding-left:15px;">${roleBadge(a.role)}</div>
        <div style="display:flex; gap:6px; padding-left:15px;">
          ${a.disabled
            ? `<button onclick="enableAgent('${a.id}')" class="btn btn-success" aria-label="Enable ${a.name}">Enable</button>`
            : `<button onclick="disableAgent('${a.id}')" class="btn btn-ghost" aria-label="Pause ${a.name}">Pause</button>`
          }
          <button onclick="kickAgent('${a.id}')" class="btn btn-danger" aria-label="Kick ${a.name}">Kick</button>
        </div>`;
      list.appendChild(card);
    });
  }

  /* ── messages ── */
  function appendMessage(m) {
    const list = document.getElementById('messages-list');
    const div = document.createElement('div');
    div.className = 'msg-row';

    if (m.system) {
      div.style.cssText = 'text-align:center; color:var(--text-3); font-size:11px; padding:2px 0; display:flex; align-items:center; gap:8px;';
      div.innerHTML = `<span style="flex:1; height:1px; background:var(--border);"></span><span style="white-space:nowrap; font-family:\'JetBrains Mono\',ui-monospace;">${m.content}</span><span style="flex:1; height:1px; background:var(--border);"></span>`;
    } else {
      const isDirect = m.to && m.to !== 'all';
      const toLabel = isDirect
        ? `<span style="color:var(--cyan); font-size:10px;">→ ${m.to}</span>`
        : `<span style="color:var(--text-3); font-size:10px; opacity:0.6;">→ all</span>`;
      div.innerHTML = `
        <div style="display:flex; align-items:baseline; gap:8px; margin-bottom:5px; flex-wrap:wrap;">
          <span style="font-weight:600; font-size:12px; color:${m.color}; font-family:\'JetBrains Mono\',ui-monospace;">${m.from}</span>
          ${toLabel}
          <span style="color:var(--text-3); font-size:10px; margin-left:auto; font-family:\'JetBrains Mono\',ui-monospace;">${ts(m.at)}</span>
        </div>
        <div class="md" style="padding-left:1px; border-left:2px solid ${m.color}40; padding-left:10px;">${marked.parse(m.content)}</div>`;
    }

    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
  }

  /* ── agent actions ── */
  function kickAgent(id) {
    if (!confirm('Remove ' + (agents[id]?.name || id) + ' from the channel?')) return;
    fetch('/dashboard/kick/' + id, {method:'POST'});
  }
  function disableAgent(id) { fetch('/dashboard/disable/' + id, {method:'POST'}); }
  function enableAgent(id)  { fetch('/dashboard/enable/'  + id, {method:'POST'}); }

  /* ── popup ── */
  function showPopup(id) {
    const a = agents[id];
    if (!a) return;
    document.getElementById('popup-name').textContent = a.name;
    document.getElementById('popup-dot').style.background = a.color;
    document.getElementById('popup-role-badge').innerHTML = roleBadge(a.role);

    const caps = (a.capabilities || []).join(', ') || '—';
    const rows = [
      ['ID', `<span style="font-family:\'JetBrains Mono\',ui-monospace; font-size:10px; word-break:break-all;">${a.id}</span>`],
      ['Status', a.disabled ? `<span style="color:var(--red);">disabled</span>` : `<span style="color:var(--green);">active</span>`],
      ['Joined', ts(a.joined_at) || '—'],
      ['Capabilities', caps],
    ];
    document.getElementById('popup-rows').innerHTML = rows.map(([l,v]) =>
      `<div class="dialog-row"><span class="dialog-label">${l}</span><span class="dialog-val">${v}</span></div>`
    ).join('');

    const btn = document.getElementById('popup-toggle-btn');
    if (a.disabled) {
      btn.textContent = 'Enable';
      btn.className = 'btn btn-success';
      btn.onclick = () => { enableAgent(id); closePopup(); };
    } else {
      btn.textContent = 'Pause';
      btn.className = 'btn btn-ghost';
      btn.onclick = () => { disableAgent(id); closePopup(); };
    }
    document.getElementById('popup-kick-btn').onclick = () => { kickAgent(id); closePopup(); };

    const overlay = document.getElementById('popup-overlay');
    overlay.style.display = 'flex';
    overlay.querySelector('.dialog').focus();
  }

  function closePopup() {
    document.getElementById('popup-overlay').style.display = 'none';
  }

  document.getElementById('popup-overlay').addEventListener('click', e => {
    if (e.target === e.currentTarget) closePopup();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closePopup();
  });

  /* ── status ── */
  function setStatus(state, text) {
    const dot = document.getElementById('status-dot');
    document.getElementById('status').textContent = text;
    dot.className = 'status-dot ' + state;
  }

  /* ── SSE ── */
  const es = new EventSource('/dashboard/events');

  es.addEventListener('message', e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;

    if (msg.type === 'snapshot') {
      msg.agents.forEach(a => { agents[a.id] = a; });
      renderAgents();
      msg.messages.forEach(appendMessage);
      setStatus('live', 'connected');
      const joinUrl = window.location.origin + '/join/TOKEN_PLACEHOLDER';
      document.getElementById('chip-text').textContent = joinUrl;
      document.getElementById('channel-chip').style.display = 'inline-flex';
    } else if (msg.type === 'agent_joined') {
      agents[msg.id] = {id:msg.id, name:msg.name, role:msg.role, color:msg.color, capabilities:msg.capabilities||[], joined_at:msg.joined_at, disabled:false};
      renderAgents();
      appendMessage({system:true, content:msg.name + ' joined'});
    } else if (msg.type === 'agent_left') {
      const name = agents[msg.id]?.name || msg.id;
      delete agents[msg.id];
      renderAgents();
      appendMessage({system:true, content:name + ' left'});
    } else if (msg.type === 'agent_disabled') {
      if (agents[msg.id]) { agents[msg.id].disabled = true; renderAgents(); }
    } else if (msg.type === 'agent_enabled') {
      if (agents[msg.id]) { agents[msg.id].disabled = false; renderAgents(); }
    } else if (msg.type === 'message') {
      appendMessage(msg);
    }
  });

  es.onerror = () => setStatus('dead', 'disconnected — retrying…');
</script>
</body>
</html>"""


async def _dashboard_html(request: Request):
    from starlette.responses import HTMLResponse
    html = _DASHBOARD_HTML.replace("TOKEN_PLACEHOLDER", TOKEN)
    return HTMLResponse(html)


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
            Route("/dashboard/kick/{agent_id}", _dashboard_kick, methods=["POST"]),
            Route("/dashboard/disable/{agent_id}", _dashboard_disable, methods=["POST"]),
            Route("/dashboard/enable/{agent_id}", _dashboard_enable, methods=["POST"]),
            Route("/dashboard", _dashboard_html),
            Route("/dashboard/events", _dashboard_events),
            Mount("/mcp", app=_mcp_app),
        ]
    )
)

# ---------------------------------------------------------------------------
