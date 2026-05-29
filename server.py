"""Power BI MCP Server - manage workspaces, datasets, refreshes, and diagnostics via stdio transport."""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from app import mcp  # noqa: E402
import tools  # noqa: E402, F401  — importing registers all @mcp.tool() decorators


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
