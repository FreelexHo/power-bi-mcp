"""TMDL (Tabular Model Definition Language) structural parser.

Pure Python parser for .tmdl files produced by Power BI Developer Mode (PBIP).
Extracts tables, columns, measures, partitions, relationships, and shared
M expressions into structured dicts suitable for JSON serialization.

No external dependencies — uses only stdlib (re, pathlib).
"""

import re
from pathlib import Path
from typing import Any

# Keys that carry no useful information for diagnostics (stripped from output)
_SKIP_KEYS = {"lineageTag"}

# ──────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────

def _indent_level(line: str) -> int:
    """Count leading tabs (TMDL uses tab indentation)."""
    n = 0
    for ch in line:
        if ch == "\t":
            n += 1
        else:
            break
    return n


def _strip_quotes(name: str) -> str:
    """Remove surrounding single quotes from TMDL names like 'My Table'."""
    name = name.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


# ──────────────────────────────────────────────
# Table file parser
# ──────────────────────────────────────────────

def parse_table_file(tmdl_path: Path) -> dict:
    """Parse a single table .tmdl file into a structured dict.

    Returns:
        {
            "name": str,
            "columns": [{"name", "dataType", "sourceColumn", "summarizeBy", "isHidden", ...}],
            "measures": [{"name", "expression", "formatString", "displayFolder", "description", ...}],
            "partitions": [{"name", "mode", "source_expression"}],
            "annotations": [{"key", "value"}],
        }
    """
    text = tmdl_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    table: dict[str, Any] = {
        "name": "",
        "columns": [],
        "measures": [],
        "partitions": [],
        "annotations": [],
    }

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and lineageTag
        if not stripped or stripped.startswith("lineageTag:"):
            i += 1
            continue

        indent = _indent_level(line)

        # ── Level 0: table declaration ──
        if indent == 0 and stripped.startswith("table "):
            table["name"] = _strip_quotes(stripped[6:].strip())
            i += 1
            continue

        # ── Level 1: column / measure / partition / annotation ──
        if indent == 1:
            if stripped.startswith("column "):
                col = _parse_column(lines, i)
                table["columns"].append(col["data"])
                i = col["next_i"]
                continue

            if stripped.startswith("measure "):
                meas = _parse_measure(lines, i)
                table["measures"].append(meas["data"])
                i = meas["next_i"]
                continue

            if stripped.startswith("partition "):
                part = _parse_partition(lines, i)
                table["partitions"].append(part["data"])
                i = part["next_i"]
                continue

            if stripped.startswith("annotation "):
                ann = _parse_annotation_line(stripped)
                if ann:
                    table["annotations"].append(ann)
                i += 1
                continue

            # Table-level property (e.g., isHidden: true)
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key, val = key.strip(), val.strip()
                if key not in _SKIP_KEYS:
                    table[key] = val
            i += 1
            continue

        i += 1

    return table


def _parse_column(lines: list[str], start: int) -> dict:
    """Parse a column block starting at `start`. Returns {"data": dict, "next_i": int}."""
    header = lines[start].strip()
    # column <name> or column '<name>'
    name = _strip_quotes(header[7:].strip())
    col: dict[str, Any] = {"name": name}
    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        indent = _indent_level(line)
        if indent <= 1:
            break  # end of this column block
        if stripped.startswith("annotation "):
            # skip column-level annotations (SummarizationSetBy etc.)
            i += 1
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if key not in _SKIP_KEYS:
                col[key] = val
        i += 1
    return {"data": col, "next_i": i}


def _parse_measure(lines: list[str], start: int) -> dict:
    """Parse a measure block starting at `start`."""
    header = lines[start].strip()
    # measure <name> = <expr_start>  OR  measure <name> =\n (multi-line)
    m = re.match(r"measure\s+(.+?)\s*=\s*(.*)", header)
    if not m:
        return {"data": {"name": header[8:].strip(), "expression": ""}, "next_i": start + 1}

    name = _strip_quotes(m.group(1))
    first_expr = m.group(2).strip()

    meas: dict[str, Any] = {"name": name}
    expr_lines: list[str] = []
    if first_expr:
        expr_lines.append(first_expr)

    i = start + 1
    collecting_expr = not first_expr  # if first line has no expr, collect multi-line

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = _indent_level(line)

        if indent <= 1:
            break  # end of this measure block

        if not stripped:
            if collecting_expr:
                expr_lines.append("")
            i += 1
            continue

        # Properties at indent 2 (formatString, displayFolder, etc.)
        if indent == 2 and ":" in stripped and not collecting_expr:
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if key not in _SKIP_KEYS:
                meas[key] = val
            i += 1
            continue

        if indent == 2 and stripped.startswith("annotation "):
            i += 1
            continue

        # Check if this is a property line after expression
        if indent == 2 and not collecting_expr:
            # Could be continuation or property
            known_props = {"formatString", "displayFolder", "description", "isHidden"}
            key_candidate = stripped.split(":")[0].strip() if ":" in stripped else ""
            if key_candidate in known_props:
                key, _, val = stripped.partition(":")
                meas[key.strip()] = val.strip()
                i += 1
                continue

        # Expression content (indent >= 3 for multi-line, or first_expr for single-line)
        if indent >= 2:
            if collecting_expr or (indent >= 3):
                # Check if this is a property, not expression
                if indent == 2 and ":" in stripped:
                    key, _, val = stripped.partition(":")
                    key, val = key.strip(), val.strip()
                    if key not in _SKIP_KEYS:
                        meas[key] = val
                    collecting_expr = False
                    i += 1
                    continue
                expr_lines.append(stripped)
                collecting_expr = True
            i += 1
            continue

        i += 1

    # Clean expression
    expr = "\n".join(expr_lines).strip()
    meas["expression"] = expr

    return {"data": meas, "next_i": i}


def _parse_partition(lines: list[str], start: int) -> dict:
    """Parse a partition block starting at `start`."""
    header = lines[start].strip()
    # partition <name> = m
    m = re.match(r"partition\s+(.+?)\s*=\s*(\w+)", header)
    name = _strip_quotes(m.group(1)) if m else header[10:].strip()
    part_type = m.group(2) if m else ""

    part: dict[str, Any] = {"name": name, "type": part_type}
    source_lines: list[str] = []
    collecting_source = False
    mode = None

    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = _indent_level(line)

        if indent <= 1:
            break

        if not stripped:
            if collecting_source:
                source_lines.append("")
            i += 1
            continue

        if indent == 2:
            if stripped.startswith("mode:"):
                mode = stripped.split(":", 1)[1].strip()
                i += 1
                continue
            if stripped == "source =":
                collecting_source = True
                i += 1
                continue
            if stripped.startswith("annotation "):
                i += 1
                continue
            if ":" in stripped and not collecting_source:
                key, _, val = stripped.partition(":")
                key, val = key.strip(), val.strip()
                if key not in _SKIP_KEYS:
                    part[key] = val
                i += 1
                continue

        if collecting_source and indent >= 3:
            # Preserve relative indentation from indent 4 (source code starts at 4 tabs)
            # Strip 4 leading tabs for clean M code
            raw = line.rstrip()
            tabs_to_strip = 4
            clean = raw[tabs_to_strip:] if len(raw) >= tabs_to_strip and raw[:tabs_to_strip] == "\t" * tabs_to_strip else raw.lstrip("\t")
            source_lines.append(clean)
            i += 1
            continue

        i += 1

    if mode:
        part["mode"] = mode
    source = "\n".join(source_lines).strip()
    if source:
        part["source_expression"] = source

    return {"data": part, "next_i": i}


def _parse_annotation_line(stripped: str) -> dict | None:
    """Parse a single annotation line: 'annotation <key> = <value>'."""
    m = re.match(r"annotation\s+(\S+)\s*=\s*(.*)", stripped)
    if m:
        return {"key": m.group(1), "value": m.group(2).strip()}
    return None


# ──────────────────────────────────────────────
# Measure extraction (convenience wrapper)
# ──────────────────────────────────────────────

def extract_measures(tmdl_path: Path) -> list[dict]:
    """Extract all measures from a table .tmdl file.

    Returns list of {"name", "expression", "table", "formatString", "displayFolder", ...}.
    """
    parsed = parse_table_file(tmdl_path)
    table_name = parsed["name"]
    measures = []
    for m in parsed["measures"]:
        m["table"] = table_name
        measures.append(m)
    return measures


# ──────────────────────────────────────────────
# Relationships file parser
# ──────────────────────────────────────────────

def parse_relationships_file(tmdl_path: Path) -> list[dict]:
    """Parse relationships.tmdl into a list of relationship dicts.

    Returns:
        [{"name", "fromTable", "fromColumn", "toTable", "toColumn",
          "crossFilteringBehavior", "isActive", "fromCardinality", ...}]
    """
    text = tmdl_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    relationships: list[dict] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        indent = _indent_level(line)
        if indent == 0 and stripped.startswith("relationship "):
            rel_name = stripped[13:].strip()
            rel: dict[str, Any] = {"name": rel_name}

            i += 1
            while i < len(lines):
                rline = lines[i]
                rstripped = rline.strip()
                rindent = _indent_level(rline)

                if not rstripped:
                    i += 1
                    continue
                if rindent == 0:
                    break  # next relationship or end

                if ":" in rstripped:
                    key, _, val = rstripped.partition(":")
                    key, val = key.strip(), val.strip()
                    if key not in _SKIP_KEYS:
                        # Split fromColumn/toColumn into table + column
                        if key == "fromColumn" and "." in val:
                            tbl, col = val.rsplit(".", 1)
                            rel["fromTable"] = _strip_quotes(tbl)
                            rel["fromColumn"] = col
                        elif key == "toColumn" and "." in val:
                            tbl, col = val.rsplit(".", 1)
                            rel["toTable"] = _strip_quotes(tbl)
                            rel["toColumn"] = col
                        else:
                            rel[key] = val
                i += 1

            relationships.append(rel)
            continue

        i += 1

    return relationships


# ──────────────────────────────────────────────
# Expressions file parser
# ──────────────────────────────────────────────

def parse_expressions_file(tmdl_path: Path) -> list[dict]:
    """Parse expressions.tmdl into a list of shared M expression dicts.

    Returns:
        [{"name", "kind": "m", "expression": str}]
    """
    text = tmdl_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    expressions: list[dict] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        indent = _indent_level(line)
        if indent == 0 and stripped.startswith("expression "):
            # expression <name> = <inline_expr>  or multi-line
            m = re.match(r"expression\s+(.+?)\s*=\s*(.*)", stripped)
            if not m:
                i += 1
                continue

            name = _strip_quotes(m.group(1))
            first_line = m.group(2).strip()

            expr_dict: dict[str, Any] = {"name": name, "kind": "m"}
            expr_lines: list[str] = []
            annotations: list[dict] = []

            if first_line:
                # Check if it's a single-line expression with meta
                expr_lines.append(first_line)

            i += 1
            while i < len(lines):
                eline = lines[i]
                estripped = eline.strip()
                eindent = _indent_level(eline)

                if eindent == 0 and estripped:
                    break  # next top-level entity

                if not estripped:
                    i += 1
                    continue

                if eindent == 1 and estripped.startswith("annotation "):
                    ann = _parse_annotation_line(estripped)
                    if ann:
                        annotations.append(ann)
                    i += 1
                    continue

                if eindent == 1 and ":" in estripped:
                    key, _, val = estripped.partition(":")
                    key, val = key.strip(), val.strip()
                    if key not in _SKIP_KEYS:
                        expr_dict[key] = val
                    i += 1
                    continue

                if eindent >= 2:
                    # M expression body
                    raw = eline.rstrip()
                    clean = raw.lstrip("\t")
                    expr_lines.append(clean)
                    i += 1
                    continue

                i += 1

            expr_dict["expression"] = "\n".join(expr_lines).strip()
            if annotations:
                expr_dict["annotations"] = annotations
            expressions.append(expr_dict)
            continue

        i += 1

    return expressions


# ──────────────────────────────────────────────
# Model overview (aggregate)
# ──────────────────────────────────────────────

def parse_model_overview(definition_dir: Path) -> dict:
    """Aggregate all TMDL files under a definition/ directory into a compact overview.

    Args:
        definition_dir: Path to the `definition/` directory containing tables/ subfolder
                        and optional relationships.tmdl, expressions.tmdl.

    Returns:
        {
            "tables": [{"name", "columns": int, "measures": int, "partitions": int, "mode": str|None}],
            "relationships": int,
            "expressions": int,
            "total_tables": int,
            "total_measures": int,
            "total_columns": int,
        }
    """
    tables_dir = definition_dir / "tables"
    rels_file = definition_dir / "relationships.tmdl"
    expr_file = definition_dir / "expressions.tmdl"

    tables_summary: list[dict] = []
    total_measures = 0
    total_columns = 0

    if tables_dir.exists():
        for tmdl in sorted(tables_dir.glob("*.tmdl")):
            try:
                parsed = parse_table_file(tmdl)
                n_cols = len(parsed["columns"])
                n_meas = len(parsed["measures"])
                total_measures += n_meas
                total_columns += n_cols
                # Get mode from first partition
                mode = None
                if parsed["partitions"]:
                    mode = parsed["partitions"][0].get("mode")
                tables_summary.append({
                    "name": parsed["name"],
                    "columns": n_cols,
                    "measures": n_meas,
                    "mode": mode,
                })
            except Exception as e:
                tables_summary.append({
                    "name": tmdl.stem,
                    "error": str(e),
                })

    rel_count = 0
    if rels_file.exists():
        try:
            rel_count = len(parse_relationships_file(rels_file))
        except Exception:
            pass

    expr_count = 0
    if expr_file.exists():
        try:
            expr_count = len(parse_expressions_file(expr_file))
        except Exception:
            pass

    return {
        "tables": tables_summary,
        "relationships": rel_count,
        "expressions": expr_count,
        "total_tables": len(tables_summary),
        "total_measures": total_measures,
        "total_columns": total_columns,
    }
