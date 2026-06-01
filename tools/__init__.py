"""Power BI MCP tools package.

Importing this package registers all tools on the shared ``mcp`` instance.
"""

from tools import (
    auth_tool,  # noqa: F401
    dataset,  # noqa: F401
    diagnose,  # noqa: F401
    query,  # noqa: F401
    refresh,  # noqa: F401
    report,  # noqa: F401
    workspace,  # noqa: F401
    local_model,  # noqa: F401
)
