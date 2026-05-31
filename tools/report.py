"""Scheduled refresh report tool."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from app import mcp
from auth import _get_json, _safe_get_json

# ---------------------------------------------------------------------------
# AEST helpers
# ---------------------------------------------------------------------------
_AEST = timezone(timedelta(hours=10))


def _utc_iso_to_aest(iso_str: str | None) -> str | None:
    """Convert UTC ISO-8601 string to 'YYYY-MM-DD HH:MM:SS AEST'."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(_AEST).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_str


def _aest_date(iso_str: str | None) -> str | None:
    """Extract AEST date (YYYY-MM-DD) from a UTC ISO string."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(_AEST).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


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


@mcp.tool()
def pbi_scheduled_refresh_report(workspace_id: str, date: str = "", format: str = "json") -> str:
    """List scheduled refresh status for every dataset that had scheduled refreshes recently.

    Scans all refreshable datasets in a workspace, identifies those with any
    Scheduled refresh in the past 7 days, and reports refresh records for the
    target date (AEST).  If a qualified dataset has no refresh on the target
    date, its most recent Scheduled refresh is shown instead (e.g. when Power BI
    auto-disabled the schedule after repeated failures).

    Each record includes a ``current_status`` snapshot of the dataset's most
    recent refresh (any type), so the reader can tell whether a past Scheduled
    failure has since been resolved by an on-demand or API-triggered refresh.

    Note: Scheduled refreshes do NOT support the Enhanced Refresh Details API, so
    error info comes from serviceExceptionJson only.

    Args:
        workspace_id: The workspace (group) ID.
        date: Optional date string (YYYY-MM-DD) in AEST. Defaults to today (AEST).
        format: Output format - "json" (default) or "table" (Markdown table).

    Returns:
        JSON report or Markdown table with flat refresh records and workspace-level summary.
    """
    target_date = date.strip() if date else datetime.now(_AEST).strftime("%Y-%m-%d")
    seven_days_ago = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    # Step 1: list all datasets
    datasets_raw = _get_json(f"/groups/{workspace_id}/datasets")
    all_datasets = datasets_raw.get("value", [])

    # Step 2: filter refreshable datasets
    refreshable = [ds for ds in all_datasets if ds.get("isRefreshable")]

    # Step 3: get all reports in workspace (one call, then map by datasetId)
    reports_raw = _safe_get_json(f"/groups/{workspace_id}/reports")
    reports_by_dataset: dict[str, list[dict]] = {}
    if isinstance(reports_raw, dict) and "value" in reports_raw:
        for r in reports_raw["value"]:
            did = r.get("datasetId")
            if did:
                reports_by_dataset.setdefault(did, []).append({
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "webUrl": r.get("webUrl"),
                })

    # Step 4: fetch history & collect flat refresh records
    refreshes: list[dict] = []
    total_completed = 0
    total_failed = 0
    total_in_progress = 0
    qualified_count = 0

    def _process_dataset(ds: dict) -> list[dict]:
        """Fetch refresh history and return records for a single dataset."""
        ds_id = ds.get("id")
        ds_name = ds.get("name", "")
        configured_by = ds.get("configuredBy", "")
        bound = reports_by_dataset.get(ds_id, [])

        history_raw = _safe_get_json(
            f"/groups/{workspace_id}/datasets/{ds_id}/refreshes?$top=30"
        )
        all_refreshes = (
            history_raw.get("value", []) if isinstance(history_raw, dict) else []
        )

        # Snapshot: most recent refresh of any type (for cross-referencing)
        latest_any = all_refreshes[0] if all_refreshes else None
        current_status = None
        if latest_any:
            current_status = {
                "refreshType": latest_any.get("refreshType"),
                "status": latest_any.get("status"),
                "startTime": _utc_iso_to_aest(latest_any.get("startTime")),
                "endTime": _utc_iso_to_aest(latest_any.get("endTime")),
            }

        # Keep only Scheduled refreshes with start_time in the last 7 days
        recent_scheduled = []
        for r in all_refreshes:
            if r.get("refreshType") != "Scheduled":
                continue
            start_utc = r.get("startTime", "")
            if not start_utc:
                continue
            r_date = _aest_date(start_utc)
            if r_date and r_date >= seven_days_ago:
                recent_scheduled.append(r)

        if not recent_scheduled:
            return []  # Not qualified

        # Prefer target-date records; fall back to the most recent record
        target_records = [
            r for r in recent_scheduled
            if _aest_date(r.get("startTime", "")) == target_date
        ]
        if not target_records:
            target_records = [recent_scheduled[0]]  # newest first from API

        results = []
        for r in target_records:
            start_utc = r.get("startTime", "")
            end_utc = r.get("endTime")
            status = r.get("status", "")

            # Parse error from serviceExceptionJson
            error = None
            error_details = None
            error_main_details = None
            svc_exc = r.get("serviceExceptionJson")
            if svc_exc:
                try:
                    exc_obj = json.loads(svc_exc) if isinstance(svc_exc, str) else svc_exc
                    # Outer layer: errorCode + errorDescription
                    error = exc_obj.get("errorCode") or exc_obj.get("error_code")
                    error_details = exc_obj.get("errorDescription")
                    # If errorDescription is itself JSON, parse for nested details
                    inner_obj = None
                    if isinstance(error_details, str) and error_details.startswith("{"):
                        try:
                            inner_obj = json.loads(error_details)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if not inner_obj and not error:
                        inner_obj = exc_obj
                    # Navigate nested structure: error.pbi.error
                    if isinstance(inner_obj, dict):
                        pbi_error = None
                        err_root = inner_obj.get("error")
                        if isinstance(err_root, dict):
                            pbi_error = err_root.get("pbi.error") or err_root
                        if not error and isinstance(pbi_error, dict):
                            error = pbi_error.get("code")
                        if not error and isinstance(err_root, dict):
                            error = err_root.get("code")
                        detail_list = []
                        if isinstance(pbi_error, dict):
                            detail_list = pbi_error.get("details") or []
                        for ed in detail_list:
                            if ed.get("code") == "DM_ErrorDetailNameCode_UnderlyingErrorMessage":
                                detail = ed.get("detail") or {}
                                error_main_details = (
                                    detail.get("value") if isinstance(detail, dict) else str(detail)
                                )
                                break
                    if not error:
                        error = str(exc_obj)
                except (json.JSONDecodeError, TypeError):
                    error = str(svc_exc)[:300]

            # Extract warnings from attempt-level serviceExceptionJson
            warning = None
            if not svc_exc:
                for attempt in r.get("refreshAttempts", []):
                    att_exc = attempt.get("serviceExceptionJson")
                    if att_exc:
                        warning = (
                            att_exc if isinstance(att_exc, str)
                            else json.dumps(att_exc, ensure_ascii=False)
                        )
                        break

            results.append({
                "dataset": ds_name,
                "owner": configured_by,
                "start_time": _utc_iso_to_aest(start_utc),
                "end_time": _utc_iso_to_aest(end_utc),
                "duration": _calc_duration(start_utc, end_utc),
                "status": status,
                "current_status": current_status,
                "error": error,
                "error_details": error_details,
                "error_main_details": error_main_details,
                "warning": warning,
                "bound_report_count": len(bound),
                "bound_reports": bound,
            })

        return results

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_process_dataset, ds): ds for ds in refreshable}
        for fut in as_completed(futures):
            records = fut.result()
            if records:
                qualified_count += 1
                for rec in records:
                    refreshes.append(rec)
                    if rec["status"] == "Completed":
                        total_completed += 1
                    elif rec["status"] == "Failed":
                        total_failed += 1
                    elif rec["status"] in ("Unknown", "InProgress"):
                        total_in_progress += 1

    out = {
        "workspace_id": workspace_id,
        "date": target_date,
        "timezone": "AEST (UTC+10)",
        "total_scheduled_datasets": qualified_count,
        "total_refreshes": len(refreshes),
        "refreshes": refreshes,
        "summary": {
            "completed": total_completed,
            "failed": total_failed,
            "in_progress": total_in_progress,
        },
    }

    if format == "table":
        return _format_as_table(out)
    return json.dumps(out, ensure_ascii=False, indent=2)


def _format_as_table(report: dict) -> str:
    """Convert the report dict to a Markdown table string."""
    lines: list[str] = []
    lines.append(f"**Workspace:** `{report['workspace_id']}` | **Date:** {report['date']} ({report['timezone']})")
    summary = report["summary"]
    lines.append(f"**Scheduled Datasets:** {report['total_scheduled_datasets']} | "
                 f"\u2705 {summary['completed']} | \u274c {summary['failed']} | \u23f3 {summary['in_progress']}")
    lines.append("")

    refreshes = report.get("refreshes", [])
    if not refreshes:
        lines.append("_No scheduled refreshes found for this date._")
        return "\n".join(lines)

    # Table header
    lines.append("| Dataset | Owner | Time (Start →End) | Duration | Status | Current Status | Error | Warning | Error Main Details | Error Details | Reports |")
    lines.append("|---------|-------|--------------------|----------|--------|----------------|-------|---------|--------------------|--------------|---------| ")

    for r in refreshes:
        error_cell = (r.get("error") or "").replace("|", "\\|")
        warning_cell = (r.get("warning") or "").replace("|", "\\|")
        error_main = (r.get("error_main_details") or "").replace("|", "\\|")
        error_detail = (r.get("error_details") or "").replace("|", "\\|")
        # Truncate long cells for table readability
        if len(warning_cell) > 80:
            warning_cell = warning_cell[:77] + "..."
        if len(error_main) > 80:
            error_main = error_main[:77] + "..."
        if len(error_detail) > 80:
            error_detail = error_detail[:77] + "..."

        start = r.get("start_time", "") or ""
        end = r.get("end_time", "") or ""
        time_cell = f"{start} →{end}" if start or end else ""

        # Format current_status as compact string
        cs = r.get("current_status")
        if cs:
            cs_type = cs.get("refreshType", "")
            cs_status = cs.get("status", "")
            cs_time = cs.get("endTime") or cs.get("startTime") or ""
            current_cell = f"{cs_type} {cs_status} @ {cs_time}" if cs_time else f"{cs_type} {cs_status}"
        else:
            current_cell = ""

        report_names = ", ".join(rpt.get("name", "") for rpt in r.get("bound_reports", []))
        if len(report_names) > 60:
            report_names = report_names[:57] + "..."

        lines.append(
            f"| {r.get('dataset', '')} "
            f"| {r.get('owner', '')} "
            f"| {time_cell} "
            f"| {r.get('duration', '') or ''} "
            f"| {r.get('status', '')} "
            f"| {current_cell} "
            f"| {error_cell} "
            f"| {warning_cell} "
            f"| {error_main} "
            f"| {error_detail} "
            f"| {report_names} |"
        )


    return "\n".join(lines)