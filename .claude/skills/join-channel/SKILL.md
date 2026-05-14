---
name: join-channel
description: Registers this agent with the AgentCouncil hub in a named channel and reads any pending inbox messages. Use when starting or resuming participation in a multi-agent collaboration. Don't use for launching the hub (see hub-start), creating group conversations (see council-discuss), or sending direct messages without first joining.
---

1. Confirm the hub is running. If not, use the hub-start skill first.

2. Determine the `channel_id` from user context (e.g. the current git repo name, sprint name, or project slug). Ask if unclear.

3. Choose an `agent_id` for this session — use a short, stable identifier like `claude-<initials>` or `claude-<repo>`. Prefer reusing the same id across sessions in the same channel.

4. Determine this agent's `capabilities` from context — e.g. `["code-review", "python"]`, `["planning"]`, `["testing"]`.

5. Register the agent:
   ```
   python scripts/register.py <agent_id> "<agent_name>" <channel_id> <cap1> [cap2 ...]
   ```

6. List other agents in the channel:
   ```
   python scripts/list_agents.py <channel_id>
   ```

7. Read pending inbox messages (messages sent while this agent was offline):
   ```
   python scripts/read_inbox.py <agent_id>
   ```

8. Report to the user: channel name, who else is present, and any inbox messages.

See `references/channel-conventions.md` for channel naming conventions.
