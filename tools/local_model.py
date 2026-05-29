"""Local PBIP semantic model reading tool."""

import json
from pathlib import Path

from app import mcp
from core.pbip_locator import _find_pbip_dataset
from core.tmdl_parser import (
    parse_table_file, parse_relationships_file,
    parse_expressions_file, parse_model_overview, extract_measures
)


@mcp.tool()
def pbi_local_model(
    dataset_name: str,
    action: str = "overview",
    name: str = "",
) -> str:
    """Read local PBIP semantic model structure (TMDL files, no Desktop connection needed).

    Requires 'pbip_root' configured in config.json.

    Actions:
      - overview:      Model summary - all tables with column/measure counts, relationship count.
      - table:         Single table detail - columns, measures, partition M expression. Requires name.
      - measure:       Single measure DAX expression + metadata. Requires name (fuzzy match across all tables).
      - expressions:   Shared M expressions (datasource definitions).
      - relationships: All model relationships with from/to table.column and cardinality.

    Args:
        dataset_name: Dataset name as it appears in Power BI Service.
        action: overview | table | measure | expressions | relationships
        name: Table or measure name (required for action=table/measure).

    Returns:
        Structured JSON with model information.
    """
    # Locate dataset
    locate = _find_pbip_dataset(dataset_name)
    if locate.get("status") != "found":
        return json.dumps(locate, ensure_ascii=False, indent=2)

    matches = locate.get("matches", [])
    if not matches:
        return json.dumps({"error": "No matches found"}, ensure_ascii=False)

    match = matches[0]
    definition_dir = match.get("definition_dir")
    if not definition_dir:
        return json.dumps({
            "error": "definition_dir_not_found",
            "hint": "SemanticModel/definition/ directory not found in PBIP folder.",
            "folder": match.get("folder"),
        }, ensure_ascii=False, indent=2)

    defn = Path(definition_dir)
    tables_dir = defn / "tables"

    action = action.strip().lower()

    # ── overview ──
    if action == "overview":
        result = parse_model_overview(defn)
        result["dataset"] = dataset_name
        result["definition_dir"] = str(defn)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── table ──
    if action == "table":
        if not name:
            return json.dumps({"error": "name is required for action='table'"}, ensure_ascii=False)
        if not tables_dir.exists():
            return json.dumps({"error": "tables/ directory not found"}, ensure_ascii=False)

        # Find table file (exact then fuzzy)
        target = _find_tmdl_file(tables_dir, name)
        if not target:
            available = [f.stem for f in sorted(tables_dir.glob("*.tmdl"))]
            return json.dumps({
                "error": f"Table '{name}' not found",
                "available_tables": available,
            }, ensure_ascii=False, indent=2)

        parsed = parse_table_file(target)
        # Compact partition: only include source_expression, not full partition metadata
        for p in parsed.get("partitions", []):
            p.pop("type", None)
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    # ── measure ──
    if action == "measure":
        if not name:
            return json.dumps({"error": "name is required for action='measure'"}, ensure_ascii=False)
        if not tables_dir.exists():
            return json.dumps({"error": "tables/ directory not found"}, ensure_ascii=False)

        name_lower = name.lower()
        # Search all tables for matching measure
        for tmdl in sorted(tables_dir.glob("*.tmdl")):
            measures = extract_measures(tmdl)
            for m in measures:
                if m["name"].lower() == name_lower:
                    return json.dumps(m, ensure_ascii=False, indent=2)

        # Fuzzy fallback: substring match
        candidates = []
        for tmdl in sorted(tables_dir.glob("*.tmdl")):
            measures = extract_measures(tmdl)
            for m in measures:
                if name_lower in m["name"].lower():
                    candidates.append(m)

        if candidates:
            if len(candidates) == 1:
                return json.dumps(candidates[0], ensure_ascii=False, indent=2)
            return json.dumps({
                "multiple_matches": [{"name": c["name"], "table": c.get("table")} for c in candidates],
                "hint": "Multiple measures match. Specify exact name.",
            }, ensure_ascii=False, indent=2)

        return json.dumps({"error": f"Measure '{name}' not found in any table"}, ensure_ascii=False)

    # ── expressions ──
    if action == "expressions":
        expr_file = defn / "expressions.tmdl"
        if not expr_file.exists():
            return json.dumps({"expressions": [], "hint": "No expressions.tmdl found"}, ensure_ascii=False)
        result = parse_expressions_file(expr_file)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── relationships ──
    if action == "relationships":
        rels_file = defn / "relationships.tmdl"
        if not rels_file.exists():
            return json.dumps({"relationships": [], "hint": "No relationships.tmdl found"}, ensure_ascii=False)
        result = parse_relationships_file(rels_file)
        return json.dumps(result, ensure_ascii=False, indent=2)

    return json.dumps({
        "error": f"Unknown action '{action}'",
        "valid_actions": ["overview", "table", "measure", "expressions", "relationships"],
    }, ensure_ascii=False)


def _find_tmdl_file(tables_dir: Path, name: str) -> Path | None:
    """Find a .tmdl file by name (exact, case-insensitive, then substring)."""
    # Exact match
    exact = tables_dir / f"{name}.tmdl"
    if exact.exists():
        return exact

    # Case-insensitive
    name_lower = name.lower()
    for f in tables_dir.glob("*.tmdl"):
        if f.stem.lower() == name_lower:
            return f

    # Substring
    for f in tables_dir.glob("*.tmdl"):
        if name_lower in f.stem.lower():
            return f

    return None
