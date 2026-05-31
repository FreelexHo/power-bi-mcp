"""Power BI MCP tools package.

Importing this package registers all tools on the shared ``mcp`` instance.
"""

from tools import auth_tool  # noqa: F401
from tools import workspace  # noqa: F401
from tools import refresh  # noqa: F401
from tools import dataset  # noqa: F401
from tools import diagnose  # noqa: F401
from tools import report  # noqa: F401
from tools import query  # noqa: F401
