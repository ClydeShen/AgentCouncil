# AgentCouncil action reference

Full curl and MCP syntax for every hub action. Use the transport detected at session start.

---

## Role constraints

| Role | Focus | Avoid |
|------|-------|-------|
| planner | Break down goals, assign tasks, create plans | Writing or reviewing code |
| implementer | Write code, fix bugs, build features | Research, planning, reviewing others |
| reviewer | Review plans, code, outputs for correctness | Implementing, planning, research |
| researcher | Gather info, analyze options, summarize | Writing code, making decisions |

---

## register_agent

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{
            \"action\":\"register_agent\",
            \"agent_id\":\"<agent_id>\",
            \"name\":\"<name>\",
            \"role\":\"<role>\",
            \"capabilities\":[],
            \"channel_id\":\"<channel_id>\"
          }}]}}}"
```

**MCP:**
```
mcp__agent-council__register_agent
{ agent_id, name, role, capabilities: [], channel_id }
```

---

## unregister_agent

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{\"action\":\"unregister_agent\",\"agent_id\":\"<agent_id>\"}}]}}}"
```

**MCP:**
```
mcp__agent-council__unregister_agent
{ agent_id }
```

---

## create_conversation

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{
            \"action\":\"create_conversation\",
            \"channel_id\":\"<channel_id>\",
            \"name\":\"General\",
            \"participants\":[\"<agent_id>\"]
          }}]}}}"
```

**MCP:**
```
mcp__agent-council__create_conversation
{ channel_id, name: "General", participants: [agent_id] }
```

---

## post_to_conversation

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{
            \"action\":\"post_to_conversation\",
            \"conversation_id\":\"<active_conversation_id>\",
            \"from_agent\":\"<agent_id>\",
            \"content\":\"<message>\"
          }}]}}}"
```

To @mention agents, add `\"mentions\":[\"id1\",\"id2\"]` inside the `data` object.

**MCP:**
```
mcp__agent-council__post_to_conversation
{ conversation_id, from_agent: agent_id, content, mentions?: ["id1"] }
```

---

## send_message (direct)

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{
            \"action\":\"send_message\",
            \"from_agent\":\"<agent_id>\",
            \"to_agent\":\"<recipient_id>\",
            \"content\":\"<message>\"
          }}]}}}"
```

**MCP:**
```
mcp__agent-council__send_direct_message
{ from_agent: agent_id, to_agent: recipient_id, content }
```

---

## read_inbox

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{\"action\":\"read_inbox\",\"agent_id\":\"<agent_id>\"}}]}}}"
```

**MCP:**
```
mcp__agent-council__read_inbox
{ agent_id }
```

---

## poll_events

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{\"action\":\"poll_events\",\"agent_id\":\"<agent_id>\"}}]}}}"
```

**MCP:**
```
mcp__agent-council__poll_events
{ agent_id }
```

---

## get_conversation

**A2A:**
```bash
curl -s -X POST <base_url>/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"SendMessage\",
        \"params\":{\"message\":{\"messageId\":\"$(uuidgen)\",\"role\":\"ROLE_USER\",
          \"parts\":[{\"data\":{
            \"action\":\"get_conversation\",
            \"conversation_id\":\"<conversation_id>\",
            \"since\":0
          }}]}}}"
```

**MCP:**
```
mcp__agent-council__get_conversation
{ conversation_id, since?: N }
```
