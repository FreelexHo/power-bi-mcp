"""Diagnostic and PBIP source-locate tools."""

import json
from typing import Any

from app import mcp
from auth import auth, _get_json, _safe_get_json
from config import POWER_BI_API
from diagnostics import _classify_refresh, _find_pbip_dataset, _read_table_tmdl
from tools.dataset import _get_dataset_info
from tools.refresh import _refresh_status, _refresh_details


@mcp.tool()
def pbi_diagnose(workspace_id: str, dataset_id: str, refresh_id: str = "") -> str:
    """One-shot diagnostic report for a Power BI dataset refresh failure.

    Pipeline:
    1. Pull dataset metadata + datasources + gateways + schedule + impacted reports.
    2. Pick a refresh to analyze: explicit refresh_id, OR latest Failed ViaEnhancedApi refresh.
    3. Fetch refresh execution details (messages, objects, attempts).
    4. Classify error: root cause table/partition, error code, underlying pattern, next actions.
    5. Add PBIP source code locate hint (folder path, expressions.tmdl, table file).

    Args:
        workspace_id: The workspace (group) ID.
        dataset_id: The dataset ID.
        refresh_id: Optional specific refresh requestId. If omitted, auto-picks latest failed Enhanced refresh.

    Returns:
        Structured JSON diagnostic report.
    """
    out: dict[str, Any] = {}

    # Step 1: dataset context (direct dict, no JSON round-trip)
    info = _get_dataset_info(workspace_id, dataset_id)
    out["dataset_summary"] = {
        "id": dataset_id,
        "name": (info.get("dataset") or {}).get("name") if isinstance(info.get("dataset"), dict) else None,
        "configuredBy": (info.get("dataset") or {}).get("configuredBy") if isinstance(info.get("dataset"), dict) else None,
        "isOnPremGatewayRequired": (info.get("dataset") or {}).get("isOnPremGatewayRequired") if isinstance(info.get("dataset"), dict) else None,
        "targetStorageMode": (info.get("dataset") or {}).get("targetStorageMode") if isinstance(info.get("dataset"), dict) else None,
    }
    out["datasources"] = info.get("datasources", [])
    out["gateways"] = info.get("gateways", [])
    out["schedule"] = info.get("schedule", {})
    out["impacted_reports"] = info.get("impacted_reports", [])
    out["pbip_locate"] = info.get("pbip_locate", {})

    # Step 2: pick target refresh (direct list, no JSON round-trip)
    history = _refresh_status(workspace_id, dataset_id, top=10)
    out["recent_refreshes"] = history

    target_refresh_id = refresh_id
    if not target_refresh_id:
        for r in history:
            if r.get("refreshType") == "ViaEnhancedApi" and r.get("status") == "Failed":
                target_refresh_id = r.get("requestId")
                break

    out["target_refresh_id"] = target_refresh_id

    # Step 3: refresh details (direct dict, no JSON round-trip)
    target_refresh = None
    if target_refresh_id:
        details = _refresh_details(workspace_id, dataset_id, target_refresh_id)
        if details.get("error"):
            out["refresh_details_error"] = details
        else:
            target_refresh = details
            out["target_refresh"] = details

    # Step 4: classify
    out["classification"] = _classify_refresh(target_refresh)

    # Step 5: PBIP table-level hint if root cause table identified
    cls = out.get("classification") or {}
    root_table = cls.get("root_cause_table")
    pbip_locate = out.get("pbip_locate") or {}
    if root_table and pbip_locate.get("status") == "found":
        matches = pbip_locate.get("matches") or []
        if matches:
            tables_dir = matches[0].get("tables_dir")
            if tables_dir:
                table_info = _read_table_tmdl(tables_dir, root_table)
                if table_info and table_info.get("found"):
                    out["root_cause_source"] = {
                        "table_name": table_info["table_name"],
                        "file": table_info["file"],
                        "partition_source_m": table_info.get("partition_source_m"),
                    }
                else:
                    out["root_cause_source"] = {
                        "table_name": root_table,
                        "found": False,
                        "tables_dir": tables_dir,
                        "hint": f"Table '{root_table}' not found in PBIP - may be system table or repo out-of-sync.",
                    }

    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
def pbi_locate_pbip(dataset_name: str, table_name: str = "") -> str:
    """Locate PBIP source code for a dataset (and optionally read a specific table's TMDL + M source).

    Requires 'pbip_root' configured in config.json (path to local PBIP repo root, e.g.
    'C:/repos/my-project/data/power-bi-report').

    Args:
        dataset_name: Dataset name as it appears in Power BI Service (e.g. 'QC Compliance Report').
                      Folder match is fuzzy: case-insensitive + non-alphanumeric stripped.
        table_name: Optional table name. If provided and dataset found, reads that table's .tmdl
                    and extracts its partition M source.

    Returns:
        JSON with {status, matches[], optional table content + partition_source_m}.
    """
    result = _find_pbip_dataset(dataset_name)
    if result.get("status") != "found" or not table_name:
        return json.dumps(result, ensure_ascii=False, indent=2)

    for m in result["matches"]:
        tables_dir = m.get("tables_dir")
        if not tables_dir:
            continue
        table_info = _read_table_tmdl(tables_dir, table_name)
        if table_info:
            m["table_lookup"] = table_info
            if table_info.get("found"):
                break  # stop at first successful match

    return json.dumps(result, ensure_ascii=False, indent=2)
