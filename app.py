"""FastMCP application instance."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Power BI",
    instructions=(
        "Power BI service management. "
        "Call pbi_auth once at the start of a session to ensure a valid token; "
        "subsequent tools will reuse it automatically. "
        "Available capabilities: workspace/dataset discovery, dataset refresh management, "
        "refresh diagnostics, scheduled refresh reporting, DAX query execution, PBIP source code lookup, and local PBIP semantic model reading (TMDL structure, measures, M expressions - no Desktop needed)."
    ),
)
