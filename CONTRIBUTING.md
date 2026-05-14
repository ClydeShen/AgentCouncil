# Contributing

## Setup

```bash
git clone https://github.com/ClydeShen/AgentCouncil
cd AgentCouncil
uv sync --group dev
```

## Running tests

```bash
uv run pytest tests/ -v
```

All tests must pass before submitting a PR.

## Submitting changes

1. Fork the repo and create a branch from `main`
2. Make your changes with tests
3. Run the test suite — all tests must pass
4. Open a pull request with a clear description of what changed and why

## Reporting bugs

Open an issue at https://github.com/ClydeShen/AgentCouncil/issues with:
- What you did
- What you expected
- What actually happened
- Python version and OS
