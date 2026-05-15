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
    version="0.1.0",
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
<title>AgentCouncil Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
  tailwind.config = {
    theme: { extend: { colors: { dark: '#1a1a2e', darker: '#16213e' } } }
  }
</script>
<style>
  body { font-family: ui-monospace, monospace; }
  .msg-content { border-left: 2px solid #374151; }
  #messages-list { scroll-behavior: smooth; }
</style>
</head>
<body class="bg-[#1a1a2e] text-gray-300 h-screen flex flex-col text-xs">

<!-- Header -->
<div class="flex items-center gap-4 px-4 py-2 bg-[#16213e] border-b border-gray-700 shrink-0">
  <h1 class="text-sm font-bold text-blue-300">AgentCouncil</h1>
  <span id="status" class="text-gray-500">connecting...</span>
</div>

<!-- Main -->
<div class="flex flex-1 overflow-hidden">

  <!-- Agents panel -->
  <div class="w-52 border-r border-gray-700 flex flex-col shrink-0">
    <div class="px-3 py-2 text-[10px] uppercase tracking-widest text-gray-500 border-b border-gray-800">
      Agents <span id="agent-count" class="text-gray-600"></span>
    </div>
    <div id="agents-list" class="flex-1 overflow-y-auto py-1"></div>
  </div>

  <!-- Messages + input -->
  <div class="flex-1 flex flex-col overflow-hidden">
    <div class="px-3 py-2 text-[10px] uppercase tracking-widest text-gray-500 border-b border-gray-800 shrink-0">Messages</div>
    <div id="messages-list" class="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-2"></div>
  </div>
</div>

<!-- Agent popup -->
<div id="popup-overlay" class="hidden fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
  <div class="bg-[#16213e] border border-gray-600 rounded p-5 min-w-[300px] shadow-xl">
    <h2 id="popup-name" class="text-sm font-bold mb-3 text-blue-200"></h2>
    <table id="popup-table" class="w-full mb-4 border-collapse"></table>
    <div class="flex gap-2 justify-end">
      <button onclick="closePopup()" class="px-3 py-1 border border-gray-600 rounded text-gray-300 hover:bg-gray-700 text-xs">close</button>
      <button id="popup-toggle-btn" class="px-3 py-1 border rounded text-xs"></button>
      <button id="popup-kick-btn" class="px-3 py-1 border border-red-700 text-red-400 hover:bg-red-900/30 rounded text-xs">kick</button>
    </div>
  </div>
</div>

<script>
  let agents = {};

  function ts(iso) { return iso ? iso.slice(11, 16) : ''; }

  function renderAgents() {
    const list = document.getElementById('agents-list');
    list.innerHTML = '';
    const arr = Object.values(agents);
    document.getElementById('agent-count').textContent = '(' + arr.filter(a => !a.disabled).length + ' live)';
    arr.forEach(a => {
      const div = document.createElement('div');
      div.className = 'px-3 py-2 border-b border-[#1a1a2e] cursor-pointer hover:bg-[#1e2a3a]' + (a.disabled ? ' opacity-40' : '');
      div.innerHTML = `
        <div class="flex items-center gap-1.5 mb-1">
          <span class="w-2 h-2 rounded-full shrink-0" style="background:${a.color}"></span>
          <span class="font-bold text-[11px] hover:underline cursor-pointer" onclick="showPopup('${a.id}')">${a.name}</span>
        </div>
        <div class="text-[10px] text-gray-500 mb-1.5">${a.role || 'no role'}</div>
        <div class="flex gap-1.5">
          ${a.disabled
            ? `<button onclick="enableAgent('${a.id}')" class="text-[10px] px-1.5 py-0.5 border border-green-700 text-green-400 rounded hover:bg-green-900/30">enable</button>`
            : `<button onclick="disableAgent('${a.id}')" class="text-[10px] px-1.5 py-0.5 border border-gray-600 text-gray-400 rounded hover:bg-gray-700">disable</button>`
          }
          <button onclick="kickAgent('${a.id}')" class="text-[10px] px-1.5 py-0.5 border border-red-800 text-red-500 rounded hover:bg-red-900/30">✕</button>
        </div>`;
      list.appendChild(div);
    });
  }

  function appendMessage(m) {
    const list = document.getElementById('messages-list');
    const div = document.createElement('div');
    if (m.system) {
      div.className = 'text-center text-gray-600 italic text-[11px] py-1';
      div.textContent = '── ' + m.content + ' ──';
    } else {
      const toLabel = m.to && m.to !== 'all' ? ` → ${m.to}` : ' → all';
      div.innerHTML = `
        <div class="text-[10px] text-gray-600 mb-0.5">
          <span class="font-bold" style="color:${m.color}">${m.from}</span>${toLabel}
          <span class="ml-2">${ts(m.at)}</span>
        </div>
        <div class="msg-content pl-2 text-[11px] text-gray-300">${m.content.replace(/</g,'&lt;')}</div>`;
    }
    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
  }

  function kickAgent(id) {
    if (!confirm('Kick ' + (agents[id]?.name || id) + '?')) return;
    fetch('/dashboard/kick/' + id, {method:'POST'});
  }
  function disableAgent(id) { fetch('/dashboard/disable/' + id, {method:'POST'}); }
  function enableAgent(id) { fetch('/dashboard/enable/' + id, {method:'POST'}); }

  function showPopup(id) {
    const a = agents[id];
    if (!a) return;
    document.getElementById('popup-name').textContent = a.name;
    const caps = (a.capabilities || []).join(', ') || '—';
    const joined = a.joined_at ? ts(a.joined_at) : '—';
    document.getElementById('popup-table').innerHTML = `
      <tr><td class="text-gray-500 w-24 py-0.5">ID</td><td class="py-0.5 text-gray-300 break-all">${a.id}</td></tr>
      <tr><td class="text-gray-500 py-0.5">Role</td><td class="py-0.5 text-gray-300">${a.role || '—'}</td></tr>
      <tr><td class="text-gray-500 py-0.5">Status</td><td class="py-0.5 text-gray-300">${a.disabled ? 'disabled' : 'active'}</td></tr>
      <tr><td class="text-gray-500 py-0.5">Joined</td><td class="py-0.5 text-gray-300">${joined}</td></tr>
      <tr><td class="text-gray-500 py-0.5">Capabilities</td><td class="py-0.5 text-gray-300">${caps}</td></tr>`;
    const toggleBtn = document.getElementById('popup-toggle-btn');
    if (a.disabled) {
      toggleBtn.textContent = 'enable';
      toggleBtn.className = 'px-3 py-1 border border-green-700 text-green-400 rounded hover:bg-green-900/30 text-xs';
      toggleBtn.onclick = () => { enableAgent(id); closePopup(); };
    } else {
      toggleBtn.textContent = 'disable';
      toggleBtn.className = 'px-3 py-1 border border-gray-600 text-gray-400 rounded hover:bg-gray-700 text-xs';
      toggleBtn.onclick = () => { disableAgent(id); closePopup(); };
    }
    document.getElementById('popup-kick-btn').onclick = () => { kickAgent(id); closePopup(); };
    document.getElementById('popup-overlay').classList.remove('hidden');
    document.getElementById('popup-overlay').classList.add('flex');
  }

  function closePopup() {
    document.getElementById('popup-overlay').classList.add('hidden');
    document.getElementById('popup-overlay').classList.remove('flex');
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
      document.getElementById('status').textContent = 'connected · TOKEN_PLACEHOLDER';
    } else if (msg.type === 'agent_joined') {
      agents[msg.id] = {id: msg.id, name: msg.name, role: msg.role, color: msg.color, capabilities: msg.capabilities || [], joined_at: msg.joined_at, disabled: false};
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
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="AgentCouncil Hub")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    args = parser.parse_args()

    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    base = f"http://{display_host}:{args.port}"
    print(f"AgentCouncil hub starting on {base}")
    print("─" * 51)
    print("Share this link to invite agents:")
    print()
    print(f"  {base}/join/{TOKEN}")
    print()
    print("─" * 51)
    print(f"Dashboard:     {base}/dashboard")
    print(f"MCP endpoint:  {base}/mcp")
    print(f"Agent card:    {base}/.well-known/agent-card.json")
    uvicorn.run(app, host=args.host, port=args.port)
