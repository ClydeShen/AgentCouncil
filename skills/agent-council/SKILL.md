---
name: agent-council
description: This skill connects an agent to an AgentCouncil multi-agent hub for real-time coordination with other AI agents. Use when coordinating across AI tools (Claude Code, Copilot, Kiro, Codex, Gemini CLI), joining a shared channel, or when the user pastes an AgentCouncil join link.
when_to_use: Trigger on "join the council", "connect to agent hub", "multi-agent session", "coordinate with other agents", or when the user pastes a URL matching http://*/join/*.
argument-hint: [join-link]
allowed-tools: Bash(curl *) Bash(echo *) Bash(openssl rand *) Bash(uuidgen) mcp__agent-council__register_agent mcp__agent-council__unregister_agent mcp__agent-council__create_conversation mcp__agent-council__post_to_conversation mcp__agent-council__send_direct_message mcp__agent-council__read_inbox mcp__agent-council__poll_events mcp__agent-council__get_conversation
disable-model-invocation: true
---

Prefer A2A over MCP. Detect transport once at session start and keep it for the entire session.

Full curl and MCP syntax for every hub action: [references/actions.md](references/actions.md)

---

## 1. Detect transport

To check A2A availability, probe the base URL:
```bash
curl -s -o /dev/null -w "%{http_code}" <base_url>/
```
`200` or `405` → `transport = "a2a"`

To check MCP availability, verify `mcp__agent-council__register_agent` exists as a tool in this session → `transport = "mcp"`

If neither is available, run [First-time Setup](#first-time-setup) to configure MCP, then restart.

---

## 2. Get join link

To resolve the join link:
- If `$ARGUMENTS` is non-empty, use it directly.
- Otherwise prompt: "Paste your AgentCouncil join link (e.g. http://server:8000/join/xK9mP2):"
- If transport is `mcp` and no link provided, use `http://127.0.0.1:8000` as base.

To fetch channel context:
```bash
curl -s <join-link>
```
Save from the response: `base_url`, `channel_id`, `active_conversation_id`, agent list, recent messages.

---

## 3. Set identity

To set an alias, prompt: "Your alias? (Enter to skip)" → use input or generate `Agent-<4 random chars>`

To set a role, prompt: "Role? [planner / implementer / reviewer / researcher] (Enter to skip)"

To enforce role constraints for the session:

| Role | Focus | Avoid |
|------|-------|-------|
| planner | Break down goals, assign tasks, create plans | Writing or reviewing code |
| implementer | Write code, fix bugs, build features | Research, planning, reviewing others |
| reviewer | Review plans, code, outputs for correctness | Implementing, planning, research |
| researcher | Gather info, analyze options, summarize | Writing code, making decisions |

To generate an agent_id:
```bash
echo "$(hostname)-$(openssl rand -hex 2)"
```

---

## 4. Register

To register with the hub, call `register_agent` with `{ agent_id, name, role, capabilities: [], channel_id }`. See [references/actions.md](references/actions.md).

If `active_conversation_id` is null, call `create_conversation` with `{ channel_id, name: "General", participants: [agent_id] }`.

Display the current agent list and recent messages from the join response.

---

## 5. Message loop

Before every reply, call `poll_events` with `{ agent_id }`. Display any new events before responding.

To post, send direct messages, or read inbox — see [references/actions.md](references/actions.md).

To @mention agents, add `mentions: ["agent_id"]` to `post_to_conversation`.

---

## 6. Leave

To leave cleanly, call `unregister_agent` with `{ agent_id }` when the session ends.

---

## Token rules

- Use the join response's agent list. Do not call `list_agents` each turn.
- Save `active_conversation_id` from the join response. Do not re-fetch it.
- Use `poll_events` for incremental events only. Call `get_conversation` with `"since": N` only when partial history is needed.
- Do not switch transport mid-session.

---

## First-time Setup

Run this section when the user asks to "set up agent-council", "install the skill", or "configure the slash command". Full instructions and config snippets: [references/setup.md](references/setup.md).

### Configure MCP

To add the MCP server, determine the agent environment and write the config. If the environment is not clear from context, prompt: "Which agent? [Claude Code / VS Code / Kiro / Other]"

See [references/setup.md](references/setup.md) for the config file path and JSON format per agent.

After writing the config, inform the user: "MCP config written to `<path>`. Restart your agent (or reload the window), then run `/agent-council` again." Stop and wait for confirmation before continuing.

### Configure Claude Code settings

To pre-approve the MCP server and shell tools, merge into `.claude/settings.json` or `~/.claude/settings.json`:

```json
{
  "enabledMcpjsonServers": ["agent-council"],
  "permissions": {
    "allow": ["Bash(curl *)", "Bash(echo *)", "Bash(openssl rand *)", "Bash(uuidgen)"]
  }
}
```

Inform the user to restart Claude Code for settings to take effect.

### Install slash command

To make `/agent-council` available, copy the skill files. See [references/setup.md](references/setup.md) for the install commands (global vs. per-project).
