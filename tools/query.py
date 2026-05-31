"""DAX query execution tool."""

import json
import logging



from app import mcp
from auth import auth
from config import POWER_BI_API

logger = logging.getLogger(__name__)


@mcp.tool()
def pbi_execute_query(
    workspace_id: str,
    dataset_id: str,
    query: str,
    impersonated_user: str = "",
    include_nulls: bool = True,
) -> str:
    """Execute a DAX query against a Power BI dataset and return the result rows.

    Uses the Execute Queries REST API (POST executeQueries).
    Only DAX queries are supported; MDX and DMV are not.

    Limitations (enforced by the Power BI service):
    - One query per call, one table per query.
    - Max 100,000 rows or 1,000,000 cell values (whichever is hit first).
    - Max 15 MB per response payload.
    - 120 requests/minute/user rate limit.

    Args:
        workspace_id: The workspace (group) ID.
        dataset_id: The dataset ID.
        query: A DAX query string, e.g. `EVALUATE SUMMARIZECOLUMNS(...)`.
        impersonated_user: Optional UPN for RLS impersonation (ignored if model has no RLS).
        include_nulls: Whether null values are serialised in the response (default True).

    Returns:
        JSON with {rows, row_count} on success, or {error, ...} on failure.
    """
    body: dict = {
        "queries": [{"query": query}],
        "serializerSettings": {"includeNulls": include_nulls},
    }
    if impersonated_user:
        body["impersonatedUserName"] = impersonated_user

    resp = auth.request(
        'post',
        f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
        content=json.dumps(body),
        timeout=60,
    )

    if resp.status_code != 200:
        return json.dumps(
            {
                "error": "query_failed",
                "status_code": resp.status_code,
                "body": resp.text[:2000],
            },
            ensure_ascii=False,
        )

    data = resp.json()

    # Extract rows from the nested response structure
    results = data.get("results", [])
    rows = []
    query_error = None
    if results:
        first = results[0]
        tables = first.get("tables", [])
        if tables:
            rows = tables[0].get("rows", [])
        query_error = first.get("error")

    out: dict = {"row_count": len(rows), "rows": rows}
    if query_error:
        out["query_error"] = query_error
    # Propagate informationProtectionLabel if present
    ipl = data.get("informationProtectionLabel")
    if ipl:
        out["informationProtectionLabel"] = ipl

    return json.dumps(out, ensure_ascii=False)
