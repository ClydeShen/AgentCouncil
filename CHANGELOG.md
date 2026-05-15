# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-05-15

### Changed
- Published to PyPI as `agentcouncil-hub` — install with `uvx agentcouncil-hub` or `pip install agentcouncil-hub`
- Refactored into `src/agentcouncil/` package layout with `cli.py` entry point
- Agent skill moved to `skills/agent-council/` at repo root
- Upgraded CI actions: `actions/checkout@v6`, `astral-sh/setup-uv@v8` (Node.js 24 compatible)
- Added GitHub Actions publish workflow — push `v*` tag to auto-publish to PyPI

## [0.4.0] - 2026-05-15

### Added
- Role-based behavioral constraints in skill: planner, implementer, reviewer, researcher — each role has explicit focus and "do NOT" rules, self-enforced for the session

### Changed
- Dashboard UI full redesign: JetBrains Mono + Sora fonts, zinc color palette, role badge chips with per-role colors, markdown rendering via marked.js, fade-in animations, improved layout and readability
- Timestamp display uses `toLocaleTimeString` for locale-aware formatting

## [0.3.0] - 2026-05-15

### Added
- Local web dashboard at `/dashboard` — real-time view of agents and messages
- Agent color coding: each agent gets a distinct color from an 8-color palette, shown in dashboard and message headers
- Disable/enable agents from dashboard — disabled agents cannot send or receive messages; re-enabling resumes from that point (no backfill)
- Kick agents from dashboard — calls `unregister_agent` and emits departure event
- `/dashboard/events` SSE stream — pushes `snapshot`, `agent_joined`, `agent_left`, `agent_disabled`, `agent_enabled`, `message` events
- `/dashboard/kick/{agent_id}`, `/dashboard/disable/{agent_id}`, `/dashboard/enable/{agent_id}` POST routes
- Dashboard URL printed on server startup
- Clickable channel chip in dashboard header copies full join URL to clipboard
- `/agent-council` skill supports both A2A (direct HTTP) and MCP — A2A takes priority when both are available

### Fixed
- `poll_events` no longer returns an agent's own sent events, preventing duplicate message re-sends
- Server startup link now shows `127.0.0.1` instead of `0.0.0.0` when bound to all interfaces

## [0.2.0] - 2026-05-15

### Added
- VS Code Copilot support via `examples/vscode-mcp.json` and `.vscode/mcp.json` (requires VS Code 1.99+)
- Kiro IDE / Kiro CLI support via `examples/kiro-mcp.json` and `.kiro/settings/mcp.json`
- All 10 hub actions now exposed as MCP tools on a single `/mcp` endpoint: `join_channel`, `register_agent`, `list_agents`, `create_conversation`, `post_to_conversation`, `get_conversation`, `send_direct_message`, `read_inbox`, `poll_events`, `unregister_agent`
- `unregister_agent` action and MCP tool — agents can now leave a channel cleanly, removing their entry from the registry, clearing inbox and event cursor, and emitting a departure event
- Structured logging across all hub actions: `[REGISTER]`, `[UNREGISTER]`, `[DM]`, `[INBOX]`, `[CONV]`, `[POST]`, `[GET_CONV]`, `[EVENT]` — timestamped and formatted for runtime tracing
- 5 new tests for `unregister_agent` (removes agent, clears inbox, clears cursor, emits leave event, unknown agent error)

### Changed
- `unregister_agent` added to A2A AgentCard skills list

## [0.1.0] - 2026-05-15

### Added
- Single-link join flow: server generates a random token on startup and prints a shareable `/join/{token}` URL
- MCP endpoint merged into `server.py` at `/mcp` — no separate `mcp_bridge.py` needed
- `poll_events` action with per-agent cursor tracking — returns only new events since last poll
- `mentions` array on `post_to_conversation` — mention events are filtered and only delivered to sender and mentioned agents
- `role` field on `register_agent` (planner / implementer / reviewer / researcher)
- `since` parameter on `get_conversation` for incremental message history
- Agent alias with `/agent-council rename` support
- 17 integration tests
- Makefile (`make start`, `make install`, `make stop`)
- GitHub Actions CI

### Changed
- Rewrote `/agent-council` skill to single-link join flow
- `post_to_conversation` stores `from_name` and `mentions` on each message

### Removed
- `mcp_bridge.py` — MCP is now served directly from `server.py`
