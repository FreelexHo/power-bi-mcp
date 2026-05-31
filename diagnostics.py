"""Diagnostic helpers: refresh classification, PBIP source locator."""

import re
from pathlib import Path
from typing import Any

from config import _get_pbip_root
from error_catalog import ERROR_CODE_CATALOG, SYSTEM_TABLE_PREFIXES, UNDERLYING_PATTERNS


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


def _normalize_name(s: str) -> str:
    """Lowercase + strip non-alphanumeric for fuzzy folder matching."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _find_pbip_dataset(dataset_name: str) -> dict:
    """Locate PBIP dataset folder by name. Returns metadata about the folder structure."""
    root = _get_pbip_root()
    if not root:
        return {
            "status": "not_configured",
            "hint": "Set 'pbip_root' in config.json next to server.py to enable PBIP source lookup.",
        }

    target = _normalize_name(dataset_name)
    if not target:
        return {"status": "no_dataset_name"}

    candidates: list[dict] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        norm = _normalize_name(child.name)
        if norm == target:
            candidates.append({"folder": child, "match": "exact"})
        elif norm.startswith(target) or target.startswith(norm):
            candidates.append({"folder": child, "match": "prefix"})
        elif target in norm or norm in target:
            candidates.append({"folder": child, "match": "substring"})

    if not candidates:
        return {
            "status": "not_in_repo",
            "dataset_name": dataset_name,
            "searched_root": str(root),
            "hint": "Dataset not version-controlled in PBIP repo (or folder name differs significantly).",
        }

    # Prefer exact > prefix > substring
    order = {"exact": 0, "prefix": 1, "substring": 2}
    candidates.sort(key=lambda c: order[c["match"]])

    matches = []
    for c in candidates:
        folder: Path = c["folder"]
        sm_dir = None
        for sub in folder.iterdir():
            if sub.is_dir() and sub.name.endswith(".SemanticModel"):
                sm_dir = sub
                break
        definition = sm_dir / "definition" if sm_dir else None
        tables_dir = definition / "tables" if definition else None
        expressions_file = definition / "expressions.tmdl" if definition else None
        model_file = definition / "model.tmdl" if definition else None

        matches.append({
            "match_type": c["match"],
            "folder": str(folder),
            "semantic_model_dir": str(sm_dir) if sm_dir else None,
            "definition_dir": str(definition) if definition and definition.exists() else None,
            "tables_dir": str(tables_dir) if tables_dir and tables_dir.exists() else None,
            "expressions_tmdl": str(expressions_file) if expressions_file and expressions_file.exists() else None,
            "model_tmdl": str(model_file) if model_file and model_file.exists() else None,
        })

    return {"status": "found", "matches": matches}


def _read_table_tmdl(tables_dir: str, table_name: str) -> dict | None:
    """Read a specific table's tmdl file, returning content + extracted M partition source."""
    if not tables_dir:
        return None
    d = Path(tables_dir)
    if not d.exists():
        return None

    # Try exact stem match
    target_file = d / f"{table_name}.tmdl"
    if not target_file.exists():
        # Fuzzy: case-insensitive stem match
        target_lower = table_name.lower()
        for f in d.glob("*.tmdl"):
            if f.stem.lower() == target_lower:
                target_file = f
                break
        else:
            # Substring fallback
            for f in d.glob("*.tmdl"):
                if target_lower in f.stem.lower():
                    target_file = f
                    break
            else:
                return {"table_name": table_name, "found": False, "tables_dir": tables_dir}

    content = target_file.read_text(encoding="utf-8", errors="replace")

    # Extract partition source M block
    partition_match = re.search(
        r"partition\s+\S+\s*=\s*m\b\s*\n(?P<body>(?:.*\n)*?)(?=\n\s*(?:partition\s|annotation\s|measure\s|column\s|table\s|\Z))",
        content,
        re.MULTILINE,
    )
    m_source = None
    if partition_match:
        m_source = partition_match.group("body").rstrip()

    return {
        "table_name": table_name,
        "found": True,
        "file": str(target_file),
        "content": content,
        "partition_source_m": m_source,
    }
