# AgentCouncil PyPI Distribution Design

**Date:** 2026-05-15  
**Status:** Approved

## Goal

Let anyone start their own AgentCouncil server with a single command: `uvx agentcouncil`.

## Scope

1. Refactor `server.py` into an installable Python package (`src/agentcouncil/`)
2. Register `agentcouncil` as a CLI entry point
3. Move the agent skill to `skills/agent-council/` in the repo root
4. Configure GitHub Actions to auto-publish to PyPI on `v*` tags
5. Update README with install instructions and manual MCP/Skill config snippets

Out of scope: `setup` command, `--server-url` flag, automated MCP/Skill injection.

## Package Structure

```
AgentCouncil/
├── src/
│   └── agentcouncil/
│       ├── __init__.py       # version string only
│       ├── server.py         # existing server.py moved here (unchanged)
│       └── cli.py            # new: parse args, call uvicorn
├── skills/
│   └── agent-council/
│       └── SKILL.md          # moved from .claude/skills/agent-council/
├── pyproject.toml
├── README.md
└── .github/workflows/publish.yml
```

## CLI Entry Point

`cli.py` is minimal — parse `--host` / `--port` and start uvicorn:

```python
def main():
    import argparse, uvicorn
    from agentcouncil.server import app
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
```

`pyproject.toml` registers the entry point:
```toml
[project.scripts]
agentcouncil = "agentcouncil.cli:main"
```

## Skill Location

The skill moves from `.claude/skills/agent-council/` to `skills/agent-council/` at repo root. This makes it discoverable on GitHub and installable via any skill manager. The `.claude/skills/` path is removed (it was a dev convenience).

## GitHub Actions — Auto Publish

`.github/workflows/publish.yml`:
- Trigger: push tag matching `v*`
- Steps: `uv build` → `uv publish` using PyPI Trusted Publisher (OIDC, no token stored in secrets)
- Requires one-time setup on PyPI: add GitHub as Trusted Publisher for this repo

## README Changes

Replace the current `git clone` install section with:

```bash
uvx agentcouncil          # run without installing
# or
pip install agentcouncil
agentcouncil --host 0.0.0.0 --port 8000
```

Add a "Configure your agent" section with copy-paste snippets for Claude Code, VS Code Copilot, Kiro — pointing to `examples/` files. Add a "Install the Skill" section pointing to `skills/agent-council/SKILL.md`.

## Migration Notes

- `server.py` imports stay unchanged; only the file location changes
- `Makefile` `start` target updated to call `agentcouncil` CLI or keep `uv run python -m agentcouncil.server`
- `uv.lock` regenerated after src layout change
