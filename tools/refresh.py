"""Refresh management tools: trigger and manage (status/details/cancel)."""

import json
import logging
import time



from app import mcp
from auth import auth, _get_json, _safe_get_json
from config import POWER_BI_API, REFRESH_POLL_INTERVAL, REFRESH_POLL_TIMEOUT
from core.refresh_classifier import _classify_refresh

logger = logging.getLogger(__name__)


@mcp.tool()
def pbi_refresh_dataset(
    workspace_id: str,
    dataset_id: str,
    refresh_type: str = "Full",
    commit_mode: str = "Transactional",
    retry_count: int = 0,
    timeout: str = "01:00:00",
    tables: list[str] | None = None,
    poll: bool = False,
    poll_interval: int = REFRESH_POLL_INTERVAL,
    poll_timeout: int = REFRESH_POLL_TIMEOUT,
) -> str:
    """Trigger an Enhanced refresh for a Power BI dataset.

    Uses the Enhanced Refresh API (refreshType=ViaEnhancedApi), which enables
    GET refresh execution details with structured messages[] and objects[]
    (partition-level failures, error codes, SourceObject pointing to Table/Column/etc).

    Args:
        workspace_id: The workspace (group) ID.
        dataset_id: The dataset ID.
        refresh_type: Full / ClearValues / Calculate / DataOnly / Automatic / Defragment (default Full).
        commit_mode: Transactional / PartialBatch (default Transactional).
        retry_count: Number of automatic retries (default 0).
        timeout: HH:MM:SS string, max 24:00:00 (default 01:00:00).
        tables: Optional list of table names to refresh, e.g. ["fact_sales", "dim_date"].
                When omitted the entire dataset is refreshed.
        poll: If True, poll refresh details until terminal (default False).
        poll_interval: Seconds between polls (default 30).
        poll_timeout: Max seconds to wait when polling (default 1800).

    Returns:
        JSON with {status, requestId, location, ...}. If poll=True also includes terminal details.
    """
    payload: dict = {
        "type": refresh_type,
        "commitMode": commit_mode,
        "retryCount": retry_count,
        "timeout": timeout,
        "notifyOption": "NoNotification",
    }
    if tables:
        payload["objects"] = [{"table": t} for t in tables]
    resp = auth.request(
        'post',
        f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes",
        content=json.dumps(payload),
        timeout=30,
    )

    if resp.status_code != 202:
        return json.dumps({
            "status": "failed_to_trigger",
            "status_code": resp.status_code,
            "body": resp.text[:1000],
        }, ensure_ascii=False)

    location = resp.headers.get("Location", "")
    request_id = location.rsplit("/", 1)[-1] if location else None
    x_ms_request_id = resp.headers.get("x-ms-request-id", "")

    result = {
        "status": "triggered",
        "requestId": request_id,
        "location": location,
        "x_ms_request_id": x_ms_request_id,
        "initiatedBy": "ViaEnhancedApi",
        "trigger_params": {
            "type": refresh_type,
            "commitMode": commit_mode,
            "retryCount": retry_count,
            "timeout": timeout,
            "tables": tables,
        },
    }
    logger.info("Enhanced refresh triggered: requestId=%s", request_id)

    if not poll or not request_id:
        return json.dumps(result, ensure_ascii=False)

    # Poll using refresh details endpoint
    start = time.time()
    check_count = 0
    logger.info("Polling every %ds (timeout %ds)...", poll_interval, poll_timeout)
    while time.time() - start < poll_timeout:
        time.sleep(poll_interval)
        check_count += 1
        elapsed = int(time.time() - start)
        try:
            details = _safe_get_json(
                f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes/{request_id}"
            )
            status = details.get("status", "Unknown") if isinstance(details, dict) else "Unknown"
            logger.info("Poll #%d (%ds): status=%s", check_count, elapsed, status)
            if status and status not in ("Unknown", "InProgress"):
                result["details"] = details
                result["poll_checks"] = check_count
                result["elapsed_seconds"] = elapsed
                result["classification"] = _classify_refresh(details if isinstance(details, dict) else None)
                return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.warning("Poll #%d (%ds): error: %s", check_count, elapsed, e)

    result["status"] = "poll_timeout"
    result["poll_checks"] = check_count
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Internal helpers used by both pbi_refresh_manage and pbi_diagnose
# ---------------------------------------------------------------------------

def _refresh_status(workspace_id: str, dataset_id: str, top: int = 5) -> list[dict]:
    """Get refresh history as a list of dicts (internal, no JSON serialization).

    Returns the full API response for each refresh entry, including
    refreshAttempts which may contain attempt-level serviceExceptionJson
    with warning details not present at the top level.
    """
    data = _get_json(f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top={top}")
    return data.get("value", [])


def _refresh_details(workspace_id: str, dataset_id: str, refresh_id: str) -> dict:
    """Get full execution details for a specific refresh (internal, no JSON serialization)."""
    resp = auth.request(
        'get',
        f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes/{refresh_id}",
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        return {
            "error": "request_failed",
            "status_code": resp.status_code,
            "hint": "403 may indicate insufficient permissions or the refresh record has expired.",
            "body": resp.text[:500],
        }
    return resp.json()


def _cancel_refresh(workspace_id: str, dataset_id: str, refresh_id: str) -> dict:
    """Cancel an in-progress Enhanced refresh (internal, no JSON serialization)."""
    resp = auth.request(
        'delete',
        f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes/{refresh_id}",
        timeout=30,
    )
    return {
        "status": "cancelled" if resp.status_code in (200, 202) else "failed",
        "status_code": resp.status_code,
        "body": resp.text[:500],
    }


@mcp.tool()
def pbi_refresh_manage(
    workspace_id: str,
    dataset_id: str,
    action: str = "status",
    refresh_id: str = "",
    top: int = 5,
) -> str:
    """Manage refresh lifecycle: view history, get execution details, or cancel.

    Actions:
      - status:  List recent refreshes (lightweight). Returns [{requestId, refreshType, startTime, endTime, status}].
      - details: Get execution details for a specific refresh (attempts, timing, status). Requires refresh_id.
                 Works for all refresh types (Enhanced, OnDemand, Scheduled). Enhanced refreshes return richer
                 data (messages, objects with partition-level detail); standard refreshes return basic timing/status.
      - cancel:  Cancel an in-progress Enhanced refresh. Requires refresh_id.

    Args:
        workspace_id: The workspace (group) ID.
        dataset_id: The dataset ID.
        action: Operation to perform - "status", "details", or "cancel".
        refresh_id: Required for "details" and "cancel" actions.
        top: Number of recent refreshes for "status" action (default 5).

    Returns:
        JSON with action-specific results.
    """
    action = action.strip().lower()

    if action == "status":
        return json.dumps(_refresh_status(workspace_id, dataset_id, top), ensure_ascii=False)

    if action == "details":
        if not refresh_id:
            return json.dumps({"error": "refresh_id is required for 'details' action"}, ensure_ascii=False)
        return json.dumps(_refresh_details(workspace_id, dataset_id, refresh_id), ensure_ascii=False)

    if action == "cancel":
        if not refresh_id:
            return json.dumps({"error": "refresh_id is required for 'cancel' action"}, ensure_ascii=False)
        return json.dumps(_cancel_refresh(workspace_id, dataset_id, refresh_id), ensure_ascii=False)

    return json.dumps({"error": f"Unknown action '{action}'. Use 'status', 'details', or 'cancel'."}, ensure_ascii=False)
