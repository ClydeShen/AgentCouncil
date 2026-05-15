# AgentCouncil setup reference

Full instructions for installing the skill and configuring Claude Code settings.

---

## Install the skill (slash command)

Copy skill files to make `/agent-council` available as a slash command.

**Global (all projects):**
```bash
mkdir -p ~/.claude/skills/agent-council/references
cp <skill-dir>/SKILL.md ~/.claude/skills/agent-council/SKILL.md
cp <skill-dir>/references/actions.md ~/.claude/skills/agent-council/references/actions.md
cp <skill-dir>/references/setup.md ~/.claude/skills/agent-council/references/setup.md
```

**Per-project only:**
```bash
mkdir -p .claude/skills/agent-council/references
cp <skill-dir>/SKILL.md .claude/skills/agent-council/SKILL.md
cp <skill-dir>/references/actions.md .claude/skills/agent-council/references/actions.md
cp <skill-dir>/references/setup.md .claude/skills/agent-council/references/setup.md
```

Restart the agent after copying. The `/agent-council` slash command is immediately available.

---

## Claude Code settings

Write or merge the following into `.claude/settings.json` (project-scoped) or `~/.claude/settings.json` (global):

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

| Key | Effect |
|-----|--------|
| `enabledMcpjsonServers` | Auto-approves the agent-council MCP server — no prompt each session |
| `permissions.allow` | Pre-approves shell tools the skill needs — session runs without interruption |

Restart Claude Code (or reload the window) for settings to take effect.

---

## MCP config by agent

When writing the MCP server entry, use the file and format for the target agent:

| Agent | Config file | Format note |
|-------|-------------|-------------|
| Claude Code (project) | `.claude/mcp.json` | standard |
| Claude Code (global) | `~/.claude/mcp.json` | standard |
| VS Code Copilot | `.vscode/mcp.json` | use `"servers"` instead of `"mcpServers"` |
| Kiro | `.kiro/settings/mcp.json` | omit `"type"` |

**Standard entry:**
```json
{
  "mcpServers": {
    "agent-council": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```
