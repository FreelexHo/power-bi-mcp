"""Refresh failure classification logic."""

import re
from typing import Any

from core.error_catalog import ERROR_CODE_CATALOG, SYSTEM_TABLE_PREFIXES, UNDERLYING_PATTERNS


def _classify_refresh(refresh: dict | None) -> dict | None:
    """Analyze refresh details and produce structured classification."""
    if not refresh:
        return None

    messages = refresh.get("messages") or []
    objects = refresh.get("objects") or []

    failed_user_tables = sorted({
        o.get("table") for o in objects
        if o.get("status") == "Failed"
        and o.get("table")
        and not o["table"].startswith(SYSTEM_TABLE_PREFIXES)
    })

    # Find root cause: earliest Error message with SourceObject.Table populated
    root_msg = None
    for m in messages:
        if m.get("type") != "Error":
            continue
        src = (m.get("location") or {}).get("SourceObject") or {}
        if src.get("Table"):
            root_msg = m
            break

    root: dict[str, Any] = {}
    if root_msg:
        src = root_msg["location"]["SourceObject"]
        root = {
            "table": src.get("Table"),
            "partition": src.get("Partition"),
            "column": src.get("Column"),
            "measure": src.get("Measure"),
            "role": src.get("Role"),
            "error_code": root_msg.get("code", ""),
            "message_snippet": (root_msg.get("message") or "")[:500],
        }

    # Match underlying error patterns across all messages
    underlying = None
    for m in messages:
        text = m.get("message") or ""
        for pattern, cat, hint in UNDERLYING_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                underlying = {"pattern": cat, "hint": hint, "snippet": text[:300]}
                break
        if underlying:
            break

    # Map error code
    error_code = root.get("error_code") or ""
    cat_label, cat_hint = ERROR_CODE_CATALOG.get(error_code, ("Unknown", ""))

    # Collect all distinct error codes appearing in messages
    all_codes = sorted({m.get("code") for m in messages if m.get("code")})

    # Build next actions
    actions: list[str] = []
    if underlying:
        if underlying["pattern"] == "EmptyColumnReference" and root.get("table"):
            actions.append(
                f"Open PBIP and inspect M expression of table '{root['table']}'. "
                f"Call pbi_locate_pbip with this table name; then grep for empty column refs: "
                f'Table[""], Field="", PromoteHeaders missing source columns.'
            )
        elif underlying["pattern"] == "CredentialsNotConfigured":
            actions.append("Reset datasource credentials in Power BI Service > Dataset Settings > Data source credentials.")
        elif underlying["pattern"] == "GatewayDown":
            actions.append("Check gateway status (Discover Gateways) and contact gatewayContactInformation.")
        elif underlying["pattern"] == "MemoryEviction":
            actions.append("Retry refresh; if recurring, scale up Premium capacity or use incremental refresh.")
        elif underlying["pattern"] == "Timeout":
            actions.append("Increase Enhanced refresh timeout parameter, or switch to incremental refresh.")
        elif underlying["pattern"] == "CapacityThrottle":
            actions.append("Reschedule refresh to off-peak hours or upgrade capacity SKU.")
        else:
            actions.append(f"Investigate underlying pattern: {underlying['hint']}")
    elif root.get("table"):
        actions.append(f"Inspect failing table '{root['table']}' - open PBIP and review its M source.")

    return {
        "status": refresh.get("status"),
        "extended_status": refresh.get("extendedStatus"),
        "root_cause_table": root.get("table"),
        "root_cause_partition": root.get("partition"),
        "root_cause_column": root.get("column"),
        "error_code": error_code,
        "error_category": cat_label,
        "error_category_hint": cat_hint,
        "underlying": underlying,
        "failed_user_tables": failed_user_tables,
        "all_error_codes": all_codes,
        "messages_count": len(messages),
        "next_actions": actions,
    }

