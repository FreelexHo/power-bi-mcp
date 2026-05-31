# Contributing to Power BI MCP Server

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/power-bi-mcp.git
cd power-bi-mcp
uv venv && uv sync
```

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check lint
uv run ruff check .

# Auto-fix lint issues
uv run ruff check --fix .

# Check formatting
uv run ruff format --check .

# Auto-format
uv run ruff format .
```

Please ensure your code passes both checks before submitting a PR.

## Making Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run lint checks: `uv run ruff check . && uv run ruff format --check .`
5. Commit with a descriptive message
6. Push and open a Pull Request

## Commit Messages

Use clear, descriptive commit messages:

- `feat: add support for incremental refresh`
- `fix: handle expired refresh token gracefully`
- `docs: clarify PBIP root configuration`
- `refactor: extract HTTP retry logic`

## Reporting Issues

When reporting bugs, please include:

- Python version (`python --version`)
- MCP client name and version (Cursor, Windsurf, etc.)
- Steps to reproduce
- Full error output (redact any tokens or tenant IDs)

## Adding New Tools

1. Create a new file in `tools/` (e.g., `tools/my_tool.py`)
2. Import and use the shared `mcp` instance from `app.py`
3. Use `auth.request()` for authenticated HTTP calls
4. Register the import in `tools/__init__.py`
5. Document the tool in `README.md`

## Security

- Never commit `config.json`, tokens, or Azure AD credentials
- Use `auth.request()` which handles token refresh automatically
- Report security vulnerabilities privately (do not open public issues)
