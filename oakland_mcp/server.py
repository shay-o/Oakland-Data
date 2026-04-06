"""MCP server for Oakland open government data via Socrata SODA API."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP(
    "oakland-data",
    instructions="Access Oakland, CA open government data — search datasets, "
    "view metadata, preview data, run queries, and get column statistics.",
)


@mcp.tool()
async def search_datasets(
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> str:
    """Search Oakland's open data portal for datasets matching keywords or topics.

    Use when the user mentions a topic, keyword, or data type they're looking for.
    Searches across dataset titles, descriptions, and tags.

    Args:
        query: Keywords to search for (e.g., "crime", "311 requests", "budget",
               "trees", "permits"). Case-insensitive.
        category: Optional category filter. Use list_categories to see valid values.
                  E.g., "Public Safety", "Financial", "Infrastructure".
        limit: Max results (1-50, default 10).

    Returns:
        Matching datasets with IDs, descriptions, and categories.
        Use the ID with get_dataset_info or preview_dataset for next steps.
    """
    return await tools.search_datasets(query, category, limit)


@mcp.tool()
async def list_categories() -> str:
    """List all dataset categories available on Oakland's open data portal.

    Use when the user wants to browse or explore without a specific topic, or
    asks "what data does Oakland have?" / "what categories are available?".

    Returns:
        List of categories with approximate dataset counts.
    """
    return await tools.list_categories()


@mcp.tool()
async def get_dataset_info(dataset_id: str) -> str:
    """Get detailed metadata and column schema for a specific Oakland dataset.

    Use after search_datasets to understand a dataset before querying it.
    Returns column names, types, row count, description, and update info.

    IMPORTANT: Call this before query_dataset so you know the exact column names.

    Args:
        dataset_id: Socrata dataset ID from search results (e.g., "ym6k-rx7a").

    Returns:
        Full metadata including all column names and types. Use these exact
        column names with query_dataset and get_column_stats.
    """
    return await tools.get_dataset_info(dataset_id)


@mcp.tool()
async def preview_dataset(dataset_id: str, limit: int = 10) -> str:
    """Get a quick sample of actual data rows from a dataset, with no filtering.

    Use to see what the data actually looks like before writing a complex query.
    Helps understand data formats, value patterns, and available fields.

    Args:
        dataset_id: Socrata dataset ID (e.g., "ym6k-rx7a").
        limit: Number of sample rows (1-50, default 10).

    Returns:
        Sample rows with all field values. Use query_dataset for filtered access.
    """
    return await tools.preview_dataset(dataset_id, limit)


@mcp.tool()
async def query_dataset(
    dataset_id: str,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    group: str | None = None,
    having: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> str:
    """Query a dataset with structured SoQL clauses (select, where, order, group).

    This is the main data access tool. Each parameter maps to a SoQL clause —
    you provide individual parts and the server builds the query.

    IMPORTANT: Call get_dataset_info first to get valid column names.

    Args:
        dataset_id: Socrata dataset ID (e.g., "ym6k-rx7a").
        select: Columns and aggregations to return.
                E.g., "crimetype, count(*) as cnt" or "address, datetime, description".
                Omit to return all columns.
        where: Filter condition using SoQL syntax.
               E.g., "crimetype = 'ROBBERY'" or "datetime > '2025-01-01'".
               Supports: =, !=, >, <, >=, <=, AND, OR, NOT, LIKE, IN, BETWEEN,
               IS NULL, IS NOT NULL, starts_with(), contains().
        order: Sort order. E.g., "datetime DESC" or "cnt DESC".
        group: Group by columns (required when using aggregation in select).
               E.g., "crimetype" or "policebeat, crimetype".
        having: Filter on aggregated values (use with group).
                E.g., "count(*) > 5".
        limit: Max rows (1-5000, default 500).
        offset: Rows to skip for pagination (default 0).

    Returns:
        Query results as formatted records. If limit rows returned, more may
        be available via pagination.
    """
    return await tools.query_dataset(
        dataset_id, select, where, order, group, having, limit, offset
    )


@mcp.tool()
async def get_column_stats(dataset_id: str, column_name: str) -> str:
    """Get distinct values and frequency counts for a column in a dataset.

    Use to understand what values exist before filtering. For example, to see
    all crime types, status values, neighborhoods, or categories in a dataset.

    IMPORTANT: column_name must exactly match a column from get_dataset_info.

    Args:
        dataset_id: Socrata dataset ID (e.g., "ym6k-rx7a").
        column_name: Exact column name to analyze (e.g., "crimetype", "status").

    Returns:
        Up to 50 distinct values sorted by frequency, with counts and percentages.
    """
    return await tools.get_column_stats(dataset_id, column_name)


def main():
    """Run the MCP server via stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
