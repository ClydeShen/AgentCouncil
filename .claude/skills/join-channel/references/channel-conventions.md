# Channel Naming Conventions

## channel_id Rules
- Lowercase letters, numbers, hyphens only
- Derive from the project context: git repo name, sprint identifier, or feature name
- Examples: `my-repo`, `sprint-15`, `auth-refactor`, `code-review-pr-42`

## agent_id Rules
- Format: `<tool>-<role>` or `<tool>-<initials>`
- Examples: `claude-planner`, `claude-alice`, `codex-coder`, `gemini-reviewer`
- Reuse the same agent_id across sessions in the same channel so peers can track history

## capabilities
- Short, lowercase slugs describing what this agent can do
- Common values: `code-review`, `planning`, `python`, `testing`, `architecture`, `docs`
- Keep to 3–5 capabilities maximum

## Multiple Agents Per Tool
Multiple Claude Code sessions can join the same channel with different agent_ids:
- `claude-alice` and `claude-bob` can both be in `sprint-15`
- Each has its own inbox; channel conversations are shared
