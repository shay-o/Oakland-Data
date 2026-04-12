"""Tool implementations for the Oakland Data MCP server.

Each function is a standalone async tool that can be called from either the MCP
server or the web app. They return formatted strings ready for LLM consumption.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import socrata
from .config import (
    MAX_LIMIT,
    DEFAULT_QUERY_LIMIT,
    DEFAULT_PREVIEW_LIMIT,
    DEFAULT_SEARCH_LIMIT,
)


def _clamp(value: int, lo: int, hi: int, default: int) -> int:
    if not isinstance(value, int) or value < lo or value > hi:
        return default
    return value


# ---------------------------------------------------------------------------
# Tool 1: search_datasets
# ---------------------------------------------------------------------------

async def search_datasets(
    query: str,
    category: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> str:
    """Search Oakland's open data portal for datasets matching keywords.

    Args:
        query: Keywords to search for (e.g., "crime", "budget", "trees").
        category: Optional category filter (e.g., "Public Safety", "Financial").
        limit: Max results to return (1-50, default 10).

    Returns:
        Formatted list of matching datasets with IDs for follow-up queries.
    """
    limit = _clamp(limit, 1, 50, DEFAULT_SEARCH_LIMIT)

    data = await socrata.discovery_search(
        query=query, category=category or "", limit=limit
    )
    results = data.get("results", [])
    total = data.get("resultSetSize", 0)

    if not results:
        return f"No datasets found matching '{query}'."

    lines = [f"Found {total} dataset(s) matching '{query}' (showing {len(results)}):\n"]
    for i, item in enumerate(results, 1):
        res = item.get("resource", {})
        cls = item.get("classification", {})
        name = res.get("name", "Untitled")
        uid = res.get("id", "unknown")
        desc = (res.get("description") or "No description")[:150]
        cat = cls.get("domain_category", "Uncategorized")
        rtype = res.get("type", "dataset")
        updated = (res.get("updatedAt") or "")[:10]

        lines.append(f"{i}. **{name}**")
        lines.append(f"   ID: `{uid}` | Type: {rtype} | Category: {cat}")
        if updated:
            lines.append(f"   Updated: {updated}")
        lines.append(f"   {desc}")
        lines.append("")

    lines.append("**Next steps:** Use `get_dataset_info` with a dataset ID to see "
                  "columns and details, or `preview_dataset` to see sample data.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: list_categories
# ---------------------------------------------------------------------------

async def list_categories() -> str:
    """List all dataset categories available on Oakland's open data portal.

    Returns:
        List of categories with dataset counts.
    """
    data = await socrata.discovery_search(query="", limit=0)

    # The Discovery API doesn't directly return facets in the same call,
    # so we do a broader search and aggregate from results.
    full_data = await socrata.discovery_search(query="", limit=200)
    results = full_data.get("results", [])

    category_counts: dict[str, int] = {}
    for item in results:
        cat = item.get("classification", {}).get("domain_category", "")
        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1

    if not category_counts:
        return "No categories found."

    sorted_cats = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)

    lines = [f"Oakland Open Data Categories ({len(sorted_cats)} categories):\n"]
    for cat, count in sorted_cats:
        lines.append(f"- **{cat}** ({count} dataset{'s' if count != 1 else ''})")

    lines.append("")
    lines.append("**Next steps:** Use `search_datasets` with a category filter to "
                  "explore datasets in a specific category.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3: get_dataset_info
# ---------------------------------------------------------------------------

async def get_dataset_info(dataset_id: str) -> str:
    """Get detailed metadata and column schema for a specific dataset.

    Args:
        dataset_id: The Socrata dataset identifier (e.g., "ym6k-rx7a").

    Returns:
        Dataset name, description, column names and types, row count, and update info.
    """
    if not dataset_id or not isinstance(dataset_id, str):
        return "Error: dataset_id must be a non-empty string."

    meta = await socrata.get_metadata(dataset_id)

    name = meta.get("name", "Untitled")
    desc = meta.get("description", "No description available.")
    attribution = meta.get("attribution", "Unknown")
    updated = (meta.get("rowsUpdatedAt") or meta.get("viewLastModified", ""))
    if isinstance(updated, (int, float)):
        from datetime import datetime, timezone
        updated = datetime.fromtimestamp(updated, tz=timezone.utc).strftime("%Y-%m-%d")
    row_count = meta.get("rowCount") or meta.get("rows", "Unknown")
    category = meta.get("category", "Uncategorized")

    columns = meta.get("columns", [])

    lines = [
        f"**{name}**\n",
        f"ID: `{dataset_id}`",
        f"Category: {category}",
        f"Attribution: {attribution}",
        f"Rows: {row_count}",
        f"Last updated: {updated}",
        f"\n**Description:**\n{desc}\n",
    ]

    location_cols: list[str] = []

    if columns:
        lines.append(f"**Columns ({len(columns)}):**\n")
        for col in columns:
            col_name = col.get("fieldName", col.get("name", "unknown"))
            col_type = col.get("dataTypeName", "unknown")
            col_desc = col.get("description", "")
            line = f"- `{col_name}` ({col_type})"
            if col_desc:
                line += f" — {col_desc[:100]}"
            if col_type == "location":
                location_cols.append(col_name)
                line += (
                    f"  ⚠ This is a composite location column. "
                    f"You CANNOT filter it directly with LIKE or =. "
                    f"Use its sub-columns instead: "
                    f"`{col_name}_address`, `{col_name}_city`, "
                    f"`{col_name}_state`, `{col_name}_zip`."
                )
            lines.append(line)
    else:
        lines.append("No column information available.")

    if location_cols:
        names = ", ".join(f"`{c}`" for c in location_cols)
        lines.append(
            f"\n**⚠ Location columns ({names}):** These store structured "
            f"address/coordinate data, not plain text. To filter, query the "
            f"sub-columns (e.g., `WHERE {location_cols[0]}_address LIKE '%BROADWAY%'`). "
            f"Sub-columns: `_address`, `_city`, `_state`, `_zip`. "
            f"For coordinates: `_latitude`, `_longitude`."
        )

    lines.append("")
    lines.append(f"**Next steps:** Use `preview_dataset(\"{dataset_id}\")` to see "
                 f"sample rows, or `query_dataset(\"{dataset_id}\", ...)` to query data.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 4: preview_dataset
# ---------------------------------------------------------------------------

async def preview_dataset(
    dataset_id: str,
    limit: int = DEFAULT_PREVIEW_LIMIT,
) -> str:
    """Get a quick sample of actual data rows from a dataset.

    Args:
        dataset_id: The Socrata dataset identifier.
        limit: Number of sample rows to return (1-50, default 10).

    Returns:
        Sample data rows formatted for readability.
    """
    if not dataset_id:
        return "Error: dataset_id is required."

    limit = _clamp(limit, 1, 50, DEFAULT_PREVIEW_LIMIT)

    try:
        rows = await socrata.soda_query(dataset_id, {"$limit": str(limit)})
    except httpx.HTTPStatusError as e:
        return f"Socrata API error ({e.response.status_code}): {e.response.text}"

    if not rows:
        return f"No data found in dataset `{dataset_id}`."

    # Get field names from first row
    fields = list(rows[0].keys())

    lines = [f"Preview of `{dataset_id}` ({len(rows)} row{'s' if len(rows) != 1 else ''}):\n"]
    lines.append(f"**Fields:** {', '.join(f'`{f}`' for f in fields[:15])}")
    if len(fields) > 15:
        lines.append(f"  ... and {len(fields) - 15} more fields")
    lines.append("")

    for i, row in enumerate(rows, 1):
        lines.append(f"**Row {i}:**")
        displayed = fields[:10]
        for f in displayed:
            val = row.get(f, "N/A")
            if isinstance(val, str) and len(val) > 120:
                val = val[:120] + "..."
            lines.append(f"  {f}: {val}")
        if len(fields) > 10:
            lines.append(f"  ... (+{len(fields) - 10} more fields)")
        lines.append("")

    lines.append("**Next steps:** Use `query_dataset` to filter, sort, or aggregate this data.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: query_dataset
# ---------------------------------------------------------------------------

async def query_dataset(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    group: str | None = None,
    having: str | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
    offset: int = 0,
) -> str:
    """Query a dataset using structured SoQL clauses.

    The server builds the SoQL query from individual clauses — you do NOT need to
    write a raw query string. Each parameter maps to a SoQL clause.

    Args:
        dataset_id: The Socrata dataset identifier.
        select: Columns to return, with optional aggregations.
                E.g., "crimetype, count(*) as cnt" or "address, datetime".
        where: Filter condition.
               E.g., "crimetype = 'ROBBERY'" or "datetime > '2025-01-01'".
        order: Sort order. E.g., "datetime DESC" or "cnt DESC".
        group: Group by columns. E.g., "crimetype".
        having: Filter on aggregated values. E.g., "count(*) > 5".
        limit: Max rows to return (1-5000, default 500).
        offset: Rows to skip for pagination (default 0).

    Returns:
        Query results formatted as records with field values.
    """
    if not dataset_id:
        return "Error: dataset_id is required."

    limit = _clamp(limit, 1, MAX_LIMIT, DEFAULT_QUERY_LIMIT)
    offset = max(0, offset)

    params: dict[str, str] = {
        "$limit": str(limit),
        "$offset": str(offset),
    }
    if select:
        params["$select"] = select
    if where:
        params["$where"] = where
    if order:
        params["$order"] = order
    if group:
        params["$group"] = group
    if having:
        params["$having"] = having

    try:
        rows = await socrata.soda_query(dataset_id, params)
    except httpx.HTTPStatusError as e:
        body = e.response.text
        return (
            f"Socrata API error ({e.response.status_code}): {body}\n\n"
            f"Hint: If a column is a `location` type, you cannot filter it directly. "
            f"Use sub-columns instead (e.g., `columnname_address LIKE '%VALUE%'`). "
            f"Run `get_dataset_info(\"{dataset_id}\")` to check column types."
        )

    if not rows:
        return "No results found for this query."

    fields = list(rows[0].keys())

    # Build a concise query summary
    query_parts = []
    if select:
        query_parts.append(f"SELECT {select}")
    if where:
        query_parts.append(f"WHERE {where}")
    if group:
        query_parts.append(f"GROUP BY {group}")
    if having:
        query_parts.append(f"HAVING {having}")
    if order:
        query_parts.append(f"ORDER BY {order}")
    query_desc = " | ".join(query_parts) if query_parts else "all fields"

    lines = [
        f"Query results from `{dataset_id}` ({len(rows)} row{'s' if len(rows) != 1 else ''}):",
        f"Query: {query_desc}",
        "",
    ]

    # Show results as records
    display_limit = min(len(rows), 25)
    for i, row in enumerate(rows[:display_limit], 1):
        parts = []
        for f in fields:
            val = row.get(f, "N/A")
            if isinstance(val, str) and len(val) > 100:
                val = val[:100] + "..."
            parts.append(f"{f}: {val}")
        lines.append(f"{i}. {' | '.join(parts)}")

    if len(rows) > display_limit:
        lines.append(f"\n... and {len(rows) - display_limit} more rows (use offset to paginate)")

    if len(rows) == limit:
        lines.append(f"\nResults may be truncated at limit={limit}. "
                     f"Use offset={offset + limit} to get the next page.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6: get_column_stats
# ---------------------------------------------------------------------------

async def get_column_stats(
    dataset_id: str,
    column_name: str,
) -> str:
    """Get distinct values and counts for a specific column in a dataset.

    Useful for understanding what values exist in a column before querying.
    For example, seeing all crime types, status values, or categories.

    Args:
        dataset_id: The Socrata dataset identifier.
        column_name: The column/field name to analyze (must match exactly).

    Returns:
        Distinct values with their counts, sorted by frequency.
    """
    if not dataset_id or not column_name:
        return "Error: both dataset_id and column_name are required."

    params = {
        "$select": f"`{column_name}`, count(*) as count",
        "$group": f"`{column_name}`",
        "$order": "count DESC",
        "$limit": "50",
    }

    try:
        rows = await socrata.soda_query(dataset_id, params)
    except httpx.HTTPStatusError as e:
        body = e.response.text
        return (
            f"Socrata API error ({e.response.status_code}): {body}\n\n"
            f"Column `{column_name}` may not exist or may not support aggregation. "
            f"If it is a `location` type, try a sub-column like `{column_name}_address`. "
            f"Use `get_dataset_info(\"{dataset_id}\")` to check column names and types."
        )

    if not rows:
        return f"No data found for column `{column_name}` in dataset `{dataset_id}`."

    total = sum(int(r.get("count", 0)) for r in rows)

    lines = [
        f"Column `{column_name}` in dataset `{dataset_id}`:",
        f"Distinct values: {len(rows)} (showing top {min(len(rows), 50)})",
        f"Total rows: {total}\n",
    ]

    for row in rows:
        val = row.get(column_name, "N/A")
        count = row.get("count", 0)
        pct = (int(count) / total * 100) if total > 0 else 0
        lines.append(f"- **{val}**: {count} ({pct:.1f}%)")

    if len(rows) == 50:
        lines.append("\n(Showing top 50 values; there may be more.)")

    return "\n".join(lines)


