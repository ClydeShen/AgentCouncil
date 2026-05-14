---
name: hub-start
description: Starts the AgentCouncil A2A hub (server.py) and optionally the MCP bridge (mcp_bridge.py). Use when launching a new multi-agent session or restarting the hub after a crash. Don't use for registering agents, managing channels, or participating in conversations — those are handled by join-channel and council-discuss.
---

1. Check if the hub is already running by running `scripts/health.sh`. If healthy, skip to step 4.

2. Start the A2A hub from the project root:
   ```
   python server.py --host 127.0.0.1 --port 8000 &
   ```
   Wait 2 seconds, then re-run `scripts/health.sh` to confirm it started.

3. If MCP clients (e.g. Claude Code via mcp_config.json) need to connect, also start the MCP bridge:
   ```
   python mcp_bridge.py --hub-url http://127.0.0.1:8000 --host 127.0.0.1 --port 8001 &
   ```

4. Report the active endpoints to the user:
   - A2A hub: `http://127.0.0.1:8000/`
   - Agent Card: `http://127.0.0.1:8000/.well-known/agent-card.json`
   - MCP bridge (if started): `http://127.0.0.1:8001/mcp`
