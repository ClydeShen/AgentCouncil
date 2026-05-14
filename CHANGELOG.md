# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
