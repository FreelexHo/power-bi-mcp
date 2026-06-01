"""Refresh management tools: trigger and manage (status/details/cancel)."""

import json
import logging
import time
from datetime import datetime

from app import mcp
from auth import _get_json, _safe_get_json, auth
from config import DISPLAY_TZ, DISPLAY_TZ_SHORT, POWER_BI_API, REFRESH_POLL_INTERVAL, REFRESH_POLL_TIMEOUT
from diagnostics import _classify_refresh

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
        "post",
        f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}/refreshes",
        content=json.dumps(payload),
        timeout=30,
    )

    if resp.status_code != 202:
        return json.dumps(
            {
                "status": "failed_to_trigger",
                "status_code": resp.status_code,
                "body": resp.text[:1000],
            },
            ensure_ascii=False,
        )

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
            details = _safe_get_json(f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes/{request_id}")
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
        "get",
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
        "delete",
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
    format: str = "json",
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
        format: Output format - "json" (default) or "table" (Markdown table with local times).

    Returns:
        JSON or Markdown table with action-specific results.
    """
    action = action.strip().lower()

    if action == "status":
        records = _refresh_status(workspace_id, dataset_id, top)
        if format == "table":
            return _format_status_table(records)
        return json.dumps(records, ensure_ascii=False)

    if action == "details":
        if not refresh_id:
            return json.dumps({"error": "refresh_id is required for 'details' action"}, ensure_ascii=False)
        detail = _refresh_details(workspace_id, dataset_id, refresh_id)
        if format == "table":
            return _format_details_table(detail)
        return json.dumps(detail, ensure_ascii=False)

    if action == "cancel":
        if not refresh_id:
            return json.dumps({"error": "refresh_id is required for 'cancel' action"}, ensure_ascii=False)
        return json.dumps(_cancel_refresh(workspace_id, dataset_id, refresh_id), ensure_ascii=False)

    return json.dumps(
        {"error": f"Unknown action '{action}'. Use 'status', 'details', or 'cancel'."},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Timezone helpers (inlined to avoid cross-module import issues)
# ---------------------------------------------------------------------------


def _utc_to_local(iso_str: str | None) -> str | None:
    """Convert UTC ISO-8601 string to local display timezone."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_str


def _calc_duration(start_iso: str | None, end_iso: str | None) -> str | None:
    """Human-readable duration between two UTC ISO strings."""
    if not start_iso or not end_iso:
        return None
    try:
        s = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        total = int((e - s).total_seconds())
        if total < 0:
            return "N/A"
        h, rem = divmod(total, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {sec}s"
        if m:
            return f"{m}m {sec}s"
        return f"{sec}s"
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Table formatting helpers for pbi_refresh_manage
# ---------------------------------------------------------------------------


def _format_status_table(records: list[dict]) -> str:
    """Format refresh history list as a Markdown table with local times."""
    if not records:
        return "_No refresh records found._"

    lines: list[str] = []
    lines.append(
        f"| # | Request ID | Type | Start ({DISPLAY_TZ_SHORT}) | End ({DISPLAY_TZ_SHORT})"
        " | Duration | Status | Initiated By |"
    )
    lines.append("|---|-----------|------|--------------|----------|----------|--------|--------------|")

    for i, r in enumerate(records, 1):
        req_id = r.get("requestId", "") or ""
        rtype = r.get("refreshType", "") or ""
        start_utc = r.get("startTime") or ""
        end_utc = r.get("endTime") or ""
        start_local = _utc_to_local(start_utc) or ""
        end_local = _utc_to_local(end_utc) or ""
        duration = _calc_duration(start_utc, end_utc) or ""
        status = r.get("status", "") or ""
        initiated = r.get("extendedStatus", "") or ""

        # Status emoji
        if status == "Completed":
            status = f"\u2705 {status}"
        elif status == "Failed":
            status = f"\u274c {status}"
        elif status in ("Unknown", "InProgress"):
            status = f"\u23f3 {status}"

        short_id = req_id[:12] + ("..." if len(req_id) > 12 else "")
        lines.append(
            f"| {i} | {short_id} | {rtype} | {start_local} | {end_local} | {duration} | {status} | {initiated} |"
        )

    return "\n".join(lines)


def _format_details_table(detail: dict) -> str:
    """Format a single refresh detail as a Markdown table with local times."""
    if "error" in detail and detail.get("error") == "request_failed":
        sc = detail.get("status_code", "")
        hint = detail.get("hint", "")
        body = detail.get("body", "")
        return f"**Error:** request_failed (HTTP {sc})\n{hint}\n{body}"

    lines: list[str] = []
    req_id = detail.get("requestId", "")
    status = detail.get("status", "")
    rtype = detail.get("refreshType", "")
    start_local = _utc_to_local(detail.get("startTime")) or ""
    end_local = _utc_to_local(detail.get("endTime")) or ""
    duration = _calc_duration(detail.get("startTime"), detail.get("endTime")) or ""

    lines.append(f"**Refresh:** `{req_id}` | **Type:** {rtype} | **Status:** {status}")
    lines.append(
        f"**Start:** {start_local} {DISPLAY_TZ_SHORT}"
        f" | **End:** {end_local} {DISPLAY_TZ_SHORT}"
        f" | **Duration:** {duration}"
    )
    lines.append("")

    # Objects table (partition-level detail for Enhanced refreshes)
    objects = detail.get("objects", [])
    if objects:
        lines.append("### Objects")
        lines.append(
            f"| Table | Partition | Status | Start ({DISPLAY_TZ_SHORT}) | End ({DISPLAY_TZ_SHORT}) | Duration |"
        )
        lines.append("|-------|-----------|--------|--------------|------------|----------|")
        for obj in objects:
            tbl = obj.get("table", "")
            part = obj.get("partition", "")
            obj_status = obj.get("status", "")
            obj_start = _utc_to_local(obj.get("startTime")) or ""
            obj_end = _utc_to_local(obj.get("endTime")) or ""
            obj_dur = _calc_duration(obj.get("startTime"), obj.get("endTime")) or ""
            lines.append(f"| {tbl} | {part} | {obj_status} | {obj_start} | {obj_end} | {obj_dur} |")
        lines.append("")

    # Messages table
    messages = detail.get("messages", [])
    if messages:
        lines.append("### Messages")
        lines.append("| Type | Message |")
        lines.append("|------|---------|")
        for msg in messages:
            msg_type = msg.get("type", "")
            msg_text = (msg.get("message", "") or "").replace("|", "\\|")
            if len(msg_text) > 120:
                msg_text = msg_text[:117] + "..."
            lines.append(f"| {msg_type} | {msg_text} |")
        lines.append("")

    # Refresh attempts
    attempts = detail.get("refreshAttempts", [])
    if attempts:
        lines.append("### Refresh Attempts")
        lines.append(f"| # | Attempt ID | Start ({DISPLAY_TZ_SHORT}) | End ({DISPLAY_TZ_SHORT}) | Type |")
        lines.append("|---|-----------|--------------|------------|------|")
        for i, att in enumerate(attempts, 1):
            att_id = att.get("attemptId", "") or ""
            att_start = _utc_to_local(att.get("startTime")) or ""
            att_end = _utc_to_local(att.get("endTime")) or ""
            att_type = att.get("type", "") or ""
            lines.append(f"| {i} | {att_id} | {att_start} | {att_end} | {att_type} |")

    return "\n".join(lines)
