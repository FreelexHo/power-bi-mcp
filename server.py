"""Power BI MCP Server - manage workspaces, datasets, refreshes, and diagnostics via stdio transport."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

import tools  # noqa: E402, F401  — importing registers all @mcp.tool() decorators
from app import mcp  # noqa: E402


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
