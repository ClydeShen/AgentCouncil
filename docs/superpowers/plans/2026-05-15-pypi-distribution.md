# PyPI Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish AgentCouncil to PyPI so anyone can run `uvx agentcouncil` to start their own server.

**Architecture:** Refactor the single `server.py` into a `src/agentcouncil/` package with a minimal `cli.py` entry point. Move the agent skill to `skills/agent-council/`. Add a GitHub Actions workflow that auto-publishes to PyPI on `v*` tags using Trusted Publisher (OIDC). Update README with one-line install and manual MCP/Skill config instructions.

**Tech Stack:** Python 3.10+, uv, uvicorn, GitHub Actions, PyPI Trusted Publisher

---

## File Map

| Action | Path |
|--------|------|
| Create | `src/agentcouncil/__init__.py` |
| Move   | `server.py` → `src/agentcouncil/server.py` |
| Create | `src/agentcouncil/cli.py` |
| Modify | `pyproject.toml` — src layout + scripts entry point |
| Move   | `.claude/skills/agent-council/SKILL.md` → `skills/agent-council/SKILL.md` |
| Modify | `tests/test_server.py` — fix import paths |
| Modify | `Makefile` — update start command |
| Create | `.github/workflows/publish.yml` |
| Modify | `README.md` — install + config sections |

---

## Task 1: Create the package skeleton

**Files:**
- Create: `src/agentcouncil/__init__.py`

- [ ] **Step 1: Create the src layout directories**

```bash
mkdir -p src/agentcouncil
```

- [ ] **Step 2: Write `__init__.py`**

```python
__version__ = "0.4.0"
```

- [ ] **Step 3: Verify the file exists**

```bash
cat src/agentcouncil/__init__.py
```

Expected output:
```
__version__ = "0.4.0"
```

- [ ] **Step 4: Commit**

```bash
git add src/agentcouncil/__init__.py
git commit -m "chore: add src/agentcouncil package skeleton"
```

---

## Task 2: Move server.py into the package

**Files:**
- Move: `server.py` → `src/agentcouncil/server.py`

- [ ] **Step 1: Move the file**

```bash
git mv server.py src/agentcouncil/server.py
```

- [ ] **Step 2: Verify the move**

```bash
ls src/agentcouncil/
```

Expected: `__init__.py  server.py`

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: move server.py into src/agentcouncil/"
```

---

## Task 3: Create the CLI entry point

**Files:**
- Create: `src/agentcouncil/cli.py`

The `__main__` block from the old `server.py` (lines 1051–1078) becomes `cli.py`. The startup print block and SSE log filter move here too.

- [ ] **Step 1: Create `cli.py`**

```python
import argparse
import logging

import uvicorn


def main() -> None:
    from agentcouncil.server import TOKEN, app

    parser = argparse.ArgumentParser(description="AgentCouncil Hub")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    base = f"http://{display_host}:{args.port}"
    print(f"AgentCouncil hub starting on {base}")
    print("─" * 51)
    print("Share this link to invite agents:")
    print()
    print(f"  {base}/join/{TOKEN}")
    print()
    print("─" * 51)
    print(f"Dashboard:     {base}/dashboard")
    print(f"MCP endpoint:  {base}/mcp")
    print(f"Agent card:    {base}/.well-known/agent-card.json")

    class _NoSSEFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "/dashboard/events" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_NoSSEFilter())
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Remove the `if __name__ == "__main__"` block from `src/agentcouncil/server.py`**

Open `src/agentcouncil/server.py`, delete everything from line 1051 to the end of the file (the `if __name__ == "__main__":` block including the argparse setup, print statements, SSE filter, and `uvicorn.run` call). The file should end after line 1050 (`app = Starlette(...)`  closing).

Verify by checking the last 5 lines of the file — there should be no `if __name__` block:

```bash
grep -n "if __name__" src/agentcouncil/server.py
```

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add src/agentcouncil/cli.py src/agentcouncil/server.py
git commit -m "feat: add cli.py entry point, remove __main__ from server.py"
```

---

## Task 4: Update pyproject.toml for src layout and CLI

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update `pyproject.toml`**

Replace the entire file with:

```toml
[project]
name = "agentcouncil"
version = "0.4.0"
description = "Universal multi-agent A2A hub — any AI coding agent can join via a single link"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "ClydeShen", url = "https://github.com/ClydeShen" }]
keywords = ["a2a", "mcp", "multi-agent", "ai", "claude", "codex"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

[project.scripts]
agentcouncil = "agentcouncil.cli:main"

[project.urls]
Homepage = "https://github.com/ClydeShen/AgentCouncil"
Repository = "https://github.com/ClydeShen/AgentCouncil"
Issues = "https://github.com/ClydeShen/AgentCouncil/issues"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agentcouncil"]

dependencies = [
    "a2a-sdk[http-server]>=1.0",
    "fastmcp>=3.0",
    "httpx>=0.27",
    "uvicorn>=0.30",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "hatchling>=1.0",
]
```

- [ ] **Step 2: Regenerate the lockfile**

```bash
uv sync --all-groups
```

Expected: lockfile updated, no errors.

- [ ] **Step 3: Verify CLI is importable**

```bash
uv run agentcouncil --help
```

Expected output includes `--host` and `--port` options.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: configure src layout and agentcouncil CLI entry point"
```

---

## Task 5: Fix test imports

**Files:**
- Modify: `tests/test_server.py`

The tests currently do `sys.path.insert(0, ...)` and import from `server`. After the move, they must import from `agentcouncil.server`.

- [ ] **Step 1: Replace the sys.path hack and bare `server` imports**

In `tests/test_server.py`, replace:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import TOKEN, _events, _cursors, _emit, _disabled, _agent_colors, _COLORS, _recent_sends
```

With:

```python
import pytest

from agentcouncil.server import TOKEN, _events, _cursors, _emit, _disabled, _agent_colors, _COLORS, _recent_sends
```

Also replace every other bare `from server import` line in the file with `from agentcouncil.server import`.

Run to find all occurrences:

```bash
grep -n "from server import\|import server" tests/test_server.py
```

Replace each one so `server` becomes `agentcouncil.server`.

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass (same count as before).

- [ ] **Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "fix: update test imports for src layout"
```

---

## Task 6: Update Makefile

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Update Makefile**

Replace the content with:

```makefile
HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: start stop install

start:
	uv run agentcouncil --host $(HOST) --port $(PORT)

install:
	uv sync

stop:
	pkill -f "agentcouncil" || true
```

- [ ] **Step 2: Verify start works**

```bash
make start &
sleep 2
curl -s http://127.0.0.1:8000/.well-known/agent-card.json | python3 -m json.tool | head -5
kill %1
```

Expected: JSON agent card output.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "chore: update Makefile to use agentcouncil CLI"
```

---

## Task 7: Move agent skill to repo root

**Files:**
- Move: `.claude/skills/agent-council/SKILL.md` → `skills/agent-council/SKILL.md`

- [ ] **Step 1: Create target directory and move**

```bash
mkdir -p skills/agent-council
git mv .claude/skills/agent-council/SKILL.md skills/agent-council/SKILL.md
```

- [ ] **Step 2: Verify**

```bash
ls skills/agent-council/
```

Expected: `SKILL.md`

- [ ] **Step 3: Check if .claude/skills/agent-council/ is now empty and remove it**

```bash
ls .claude/skills/agent-council/ 2>/dev/null && echo "not empty" || git rm -r .claude/skills/agent-council/
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: move agent skill from .claude/skills/ to skills/"
```

---

## Task 8: Add GitHub Actions publish workflow

**Files:**
- Create: `.github/workflows/publish.yml`

This uses PyPI Trusted Publisher (OIDC) — no API token stored in GitHub secrets. Requires one-time setup on PyPI after the workflow is merged (see note at end of task).

- [ ] **Step 1: Create `publish.yml`**

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - name: Build package
        run: uv build

      - name: Publish to PyPI
        run: uv publish
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "ci: add PyPI publish workflow on v* tags"
```

- [ ] **Step 3: One-time PyPI Trusted Publisher setup (manual, do once)**

Go to https://pypi.org/manage/account/publishing/ and add a new Trusted Publisher:
- PyPI project name: `agentcouncil`
- Owner: `ClydeShen`
- Repository: `AgentCouncil`
- Workflow filename: `publish.yml`
- Environment name: `pypi`

Also create a GitHub Environment named `pypi` in the repo settings (Settings → Environments → New environment → `pypi`).

---

## Task 9: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the Install section**

Find the current `## Install` section and replace it with:

```markdown
## Install

```bash
uvx agentcouncil
```

Or install permanently:

```bash
pip install agentcouncil
agentcouncil --host 0.0.0.0 --port 8000
```

**Requirements:** Python 3.10+
```

- [ ] **Step 2: Replace the Start section**

Find the current `## Start` section and replace it with:

```markdown
## Start

```bash
agentcouncil                         # binds to 0.0.0.0:8000
agentcouncil --port 9000             # custom port
agentcouncil --host 127.0.0.1        # localhost only
```
```

- [ ] **Step 3: Add Skill install section**

After the existing Configure section, add:

```markdown
### Agent Skill (Claude Code / Gemini CLI)

Copy the skill to your agent's skills directory:

```bash
# Claude Code (global)
cp skills/agent-council/SKILL.md ~/.claude/skills/agent-council/SKILL.md

# Claude Code (project)
cp skills/agent-council/SKILL.md .claude/skills/agent-council/SKILL.md
```

The skill teaches your agent to join AgentCouncil channels and collaborate with other agents. After copying, restart your agent.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README with uvx install and skill setup instructions"
```

---

## Task 10: Final verification and push

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Verify package builds cleanly**

```bash
uv build
ls dist/
```

Expected: `agentcouncil-0.4.0-py3-none-any.whl` and `agentcouncil-0.4.0.tar.gz`

- [ ] **Step 3: Smoke-test the built wheel**

```bash
pip install dist/agentcouncil-0.4.0-py3-none-any.whl --force-reinstall
agentcouncil --help
```

Expected: help text with `--host` and `--port`.

- [ ] **Step 4: Push to remote and tag**

```bash
git push origin main
git tag v0.4.1
git push origin v0.4.1
```

The `v0.4.1` tag triggers the GitHub Actions publish workflow. Monitor at: https://github.com/ClydeShen/AgentCouncil/actions

> Note: increment the tag only if v0.4.0 was already published. If not, re-tag as v0.4.0.
