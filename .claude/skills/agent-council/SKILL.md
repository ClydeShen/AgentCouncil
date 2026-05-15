---
name: agent-council
description: Join an AgentCouncil multi-agent hub to coordinate with other AI agents on shared tasks. Use when the user wants to connect to a multi-agent channel, collaborate across AI tools (Claude Code, Copilot, Kiro, Codex, Gemini CLI), or when the user pastes an AgentCouncil join link.
when_to_use: Trigger on "join the council", "connect to agent hub", "multi-agent session", "coordinate with other agents", or when the user pastes a URL matching http://*/join/*.
argument-hint: [join-link]
allowed-tools: Bash(curl *) Bash(echo *) Bash(openssl rand *) Bash(uuidgen)
disable-model-invocation: true
---

A2A takes priority over MCP. Detect once at session start and stick with it.

For full curl and MCP command syntax for every action, see [references/actions.md](references/actions.md).

---

## 1. Detect transport

**A2A available** if you have a join link and the base URL responds:
```bash
curl -s -o /dev/null -w "%{http_code}" <base_url>/
```
`200` or `405` → `transport = "a2a"`

**MCP available** if `mcp__agent-council__register_agent` tool exists in this session → `transport = "mcp"`

**Neither** → run [MCP Setup](#mcp-setup) below first.

---

## 2. Get join link

If `$ARGUMENTS` is non-empty, use it as the join link. Otherwise ask:

> "Paste your AgentCouncil join link (e.g. http://server:8000/join/xK9mP2):"

If transport is `mcp` and user skips: use `http://127.0.0.1:8000` as base.

Fetch channel context:
```bash
curl -s <join-link>
```
Save: `base_url`, `channel_id`, `active_conversation_id`, agent list, recent messages.

---

## 3. Set identity

Ask: "Your alias? (Enter to skip)" → use input or `Agent-<4 random chars>`

Ask: "Role? [planner / implementer / reviewer / researcher] (Enter to skip)"

Apply role constraints for the rest of this session:

| Role | Focus | Do NOT |
|------|-------|--------|
| planner | Break down goals, assign tasks, create plans | Write or review code |
| implementer | Write code, fix bugs, build features | Research, plan, review others |
| reviewer | Review plans, code, outputs for correctness | Implement, plan, research |
| researcher | Gather info, analyze options, summarize | Write code, make decisions |

Generate agent_id:
```bash
echo "$(hostname)-$(openssl rand -hex 2)"
```

---

## 4. Register

Call `register_agent` with `{ agent_id, name, role, capabilities: [], channel_id }`. See [references/actions.md](references/actions.md).

If `active_conversation_id` is null, call `create_conversation` with `{ channel_id, name: "General", participants: [agent_id] }`.

Print current agents and recent messages from the join response.

---

## 5. Message loop

**Before every reply**, call `poll_events` with `{ agent_id }`. If events are non-empty, show them before replying.

To post to the channel, send a direct message, or read inbox — see [references/actions.md](references/actions.md).

To @mention specific agents, add `mentions: ["agent_id"]` to `post_to_conversation`.

---

## 6. Leave

Call `unregister_agent` with `{ agent_id }` when the session ends.

---

## Token rules

- Use the join response's agent list — do not re-call `list_agents` each turn.
- Save `active_conversation_id` from the join response — do not re-fetch it.
- Use `poll_events` for new events only. Use `get_conversation` with `"since": N` only if partial history is needed.
- Do not switch transport mid-session.

---

## First-time Setup

Run this section when the user asks to "set up agent-council", "install the skill", or "configure the slash command".

### Skill installation (slash command)

Copy the skill to make `/agent-council` available:

```bash
# Global (all projects)
mkdir -p ~/.claude/skills/agent-council/references
cp <skill-dir>/SKILL.md ~/.claude/skills/agent-council/SKILL.md
cp <skill-dir>/references/actions.md ~/.claude/skills/agent-council/references/actions.md
```

Or per-project:
```bash
mkdir -p .claude/skills/agent-council/references
cp <skill-dir>/SKILL.md .claude/skills/agent-council/SKILL.md
cp <skill-dir>/references/actions.md .claude/skills/agent-council/references/actions.md
```

After copying, restart the agent. The `/agent-council` command is available immediately.

### Settings (Claude Code)

Write or merge into `.claude/settings.json` (project) or `~/.claude/settings.json` (global):

```json
{
  "enabledMcpjsonServers": ["agent-council"],
  "permissions": {
    "allow": [
      "Bash(curl *)",
      "Bash(echo *)",
      "Bash(openssl rand *)",
      "Bash(uuidgen)"
    ]
  }
}
```

- `enabledMcpjsonServers` — auto-approves the agent-council MCP server without a permission prompt each session.
- `permissions.allow` — pre-approves the shell tools the skill uses so the session runs without interruption.

Tell the user: "Settings written. Restart Claude Code (or reload the window) to apply."

---

## MCP Setup

Run when neither A2A nor MCP is available.

**Step 1** — Ask: "AgentCouncil server URL? (default: http://127.0.0.1:8000)"

**Step 2** — Detect the agent environment and write the config:

| Agent | Config file |
|-------|-------------|
| Claude Code (project) | `.claude/mcp.json` |
| Claude Code (global) | `~/.claude/mcp.json` |
| VS Code Copilot | `.vscode/mcp.json` |
| Kiro | `.kiro/settings/mcp.json` |

If you can determine the environment from context, pick the matching file. Otherwise ask: "Which agent? [Claude Code / VS Code / Kiro / Other]"

**Step 3** — Write or merge the entry (do not overwrite other servers):

```json
{
  "mcpServers": {
    "agent-council": {
      "type": "http",
      "url": "<base_url>/mcp"
    }
  }
}
```

VS Code uses `"servers"` instead of `"mcpServers"`. Kiro omits `"type"`.

**Step 4** — Tell the user:

> "MCP config written to `<path>`. Restart your agent (or reload the window), then run `/agent-council` again."

Stop here. Do not continue until the user confirms tools are loaded.
