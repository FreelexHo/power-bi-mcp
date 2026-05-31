"""Dataset metadata aggregation tool."""

import json
from typing import Any

from app import mcp
from auth import _safe_get_json
from diagnostics import _find_pbip_dataset


def _get_dataset_info(workspace_id: str, dataset_id: str) -> dict[str, Any]:
    """Aggregate dataset metadata (internal, returns dict — no JSON serialization).

    Returns:
        dict: {dataset, datasources, gateways, schedule, impacted_reports, pbip_locate}
    """
    out: dict[str, Any] = {}
    out["dataset"] = _safe_get_json(f"/groups/{workspace_id}/datasets/{dataset_id}")
    ds = _safe_get_json(f"/groups/{workspace_id}/datasets/{dataset_id}/datasources")
    out["datasources"] = ds.get("value", []) if isinstance(ds, dict) else ds
    gw = _safe_get_json(f"/groups/{workspace_id}/datasets/{dataset_id}/Default.DiscoverGateways")
    out["gateways"] = gw.get("value", []) if isinstance(gw, dict) else gw
    out["schedule"] = _safe_get_json(f"/groups/{workspace_id}/datasets/{dataset_id}/refreshSchedule")

    # Impacted reports (reports in the same workspace bound to this datasetId)
    reports = _safe_get_json(f"/groups/{workspace_id}/reports")
    if isinstance(reports, dict) and "value" in reports:
        out["impacted_reports"] = [
            {"id": r.get("id"), "name": r.get("name"), "webUrl": r.get("webUrl")}
            for r in reports["value"]
            if r.get("datasetId") == dataset_id
        ]
    else:
        out["impacted_reports"] = reports

    # PBIP source locate hint
    dataset_name = ""
    if isinstance(out["dataset"], dict):
        dataset_name = out["dataset"].get("name", "")
    out["pbip_locate"] = _find_pbip_dataset(dataset_name)

    return out


@mcp.tool()
def pbi_dataset_info(workspace_id: str, dataset_id: str) -> str:
    """Aggregate dataset metadata + datasources + bound gateways + refresh schedule + impacted reports.

    Single call that returns everything needed to understand dataset configuration without
    making multiple round-trips. Useful for diagnostics and context-gathering.

    Args:
        workspace_id: The workspace (group) ID.
        dataset_id: The dataset ID.

    Returns:
        JSON object: {dataset, datasources, gateways, schedule, impacted_reports, pbip_locate}
    """
    return json.dumps(_get_dataset_info(workspace_id, dataset_id), ensure_ascii=False, indent=2)
