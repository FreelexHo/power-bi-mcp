"""Workspace and dataset listing tools."""

import json

from app import mcp
from auth import _get_json


@mcp.tool()
def pbi_list_workspaces(filter: str = "") -> str:
    """List Power BI workspaces accessible to the authenticated user.

    Args:
        filter: Optional name filter (case-insensitive substring match).

    Returns:
        JSON array of workspaces: [{id, name, type, state, isOnDedicatedCapacity, capacityId}]
    """
    data = _get_json("/groups")
    workspaces = data.get("value", [])
    if filter:
        fl = filter.lower()
        workspaces = [w for w in workspaces if fl in w.get("name", "").lower()]
    result = [
        {
            "id": w.get("id"),
            "name": w.get("name"),
            "type": w.get("type"),
            "state": w.get("state"),
            "isOnDedicatedCapacity": w.get("isOnDedicatedCapacity"),
            "capacityId": w.get("capacityId"),
        }
        for w in workspaces
    ]
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def pbi_list_datasets(workspace_id: str) -> str:
    """List datasets in a Power BI workspace.

    Args:
        workspace_id: The workspace (group) ID.

    Returns:
        JSON array: [{id, name, configuredBy, isRefreshable, isOnPremGatewayRequired}]
    """
    data = _get_json(f"/groups/{workspace_id}/datasets")
    result = [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "configuredBy": d.get("configuredBy"),
            "isRefreshable": d.get("isRefreshable"),
            "isOnPremGatewayRequired": d.get("isOnPremGatewayRequired"),
        }
        for d in data.get("value", [])
    ]
    return json.dumps(result, ensure_ascii=False)
