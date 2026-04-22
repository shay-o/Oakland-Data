"""Unit tests for oakland_mcp.tools with mocked HTTP responses.

Each test uses respx to intercept httpx requests so no real network calls are made.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from oakland_mcp import tools
from oakland_mcp.config import DISCOVERY_API_BASE, METADATA_BASE, SODA_BASE

from .conftest import (
    FAKE_METADATA_NO_LOCATION,
    FAKE_METADATA_WITH_LOCATION,
    FAKE_QUERY_ROWS,
    FAKE_SEARCH_RESULTS,
    SOCRATA_400_LOCATION_ERROR,
)


# ===================================================================
# get_dataset_info
# ===================================================================


class TestGetDatasetInfo:
    """Tests for the get_dataset_info tool."""

    async def test_location_columns_get_warning(self, mock_api):
        mock_api.get(f"{METADATA_BASE}/4jcx-enxf.json").respond(
            200, json=FAKE_METADATA_WITH_LOCATION
        )
        result = await tools.get_dataset_info("4jcx-enxf")

        assert "⚠" in result
        assert "stname_address" in result
        assert "stname_city" in result
        assert "location_1_address" in result
        assert "CANNOT filter it directly" in result

    async def test_location_summary_block_present(self, mock_api):
        mock_api.get(f"{METADATA_BASE}/4jcx-enxf.json").respond(
            200, json=FAKE_METADATA_WITH_LOCATION
        )
        result = await tools.get_dataset_info("4jcx-enxf")

        assert "Location columns" in result
        assert "WHERE stname_address LIKE" in result

    async def test_no_warning_when_no_location_columns(self, mock_api):
        mock_api.get(f"{METADATA_BASE}/ym6k-rx7a.json").respond(
            200, json=FAKE_METADATA_NO_LOCATION
        )
        result = await tools.get_dataset_info("ym6k-rx7a")

        assert "⚠" not in result
        assert "Location columns" not in result
        assert "crimetype" in result
        assert "datetime" in result

    async def test_basic_metadata_fields(self, mock_api):
        mock_api.get(f"{METADATA_BASE}/4jcx-enxf.json").respond(
            200, json=FAKE_METADATA_WITH_LOCATION
        )
        result = await tools.get_dataset_info("4jcx-enxf")

        assert "Street Trees" in result
        assert "4jcx-enxf" in result
        assert "Environmental" in result
        assert "Oakland Public Works" in result

    async def test_empty_dataset_id_returns_error(self, mock_api):
        result = await tools.get_dataset_info("")
        assert "Error" in result

    async def test_column_description_included(self, mock_api):
        mock_api.get(f"{METADATA_BASE}/4jcx-enxf.json").respond(
            200, json=FAKE_METADATA_WITH_LOCATION
        )
        result = await tools.get_dataset_info("4jcx-enxf")

        assert "Tree species name" in result


# ===================================================================
# query_dataset
# ===================================================================


class TestQueryDataset:
    """Tests for the query_dataset tool."""

    async def test_successful_query(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(
            200, json=FAKE_QUERY_ROWS
        )
        result = await tools.query_dataset("4jcx-enxf", select="species, objectid")

        assert "Liquidambar" in result
        assert "3 rows" in result
        assert "SELECT species, objectid" in result

    async def test_400_returns_socrata_error_body(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(
            400, json=SOCRATA_400_LOCATION_ERROR
        )
        result = await tools.query_dataset(
            "4jcx-enxf", where="stname LIKE '%PARK%'"
        )

        assert "type-mismatch" in result
        assert "400" in result

    async def test_400_includes_self_correction_hint(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(
            400, json=SOCRATA_400_LOCATION_ERROR
        )
        result = await tools.query_dataset(
            "4jcx-enxf", where="stname LIKE '%PARK%'"
        )

        assert "sub-columns" in result.lower() or "sub-column" in result.lower()
        assert "get_dataset_info" in result

    async def test_where_clause_in_query_summary(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(
            200, json=FAKE_QUERY_ROWS
        )
        result = await tools.query_dataset(
            "4jcx-enxf", where="stname_address LIKE '%PARK%'"
        )

        assert "WHERE stname_address LIKE '%PARK%'" in result

    async def test_empty_results(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(200, json=[])

        result = await tools.query_dataset("4jcx-enxf", where="species='Nonexistent'")

        assert "No results found" in result

    async def test_empty_dataset_id_returns_error(self, mock_api):
        result = await tools.query_dataset("")
        assert "Error" in result

    async def test_limit_clamped_to_max(self, mock_api):
        """Limit above MAX_LIMIT should be clamped to the default."""
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(200, json=FAKE_QUERY_ROWS)
        result = await tools.query_dataset("4jcx-enxf", limit=99999)

        assert "3 rows" in result

    async def test_pagination_hint_when_at_limit(self, mock_api):
        rows = [{"species": f"tree_{i}"} for i in range(3)]
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(200, json=rows)

        result = await tools.query_dataset("4jcx-enxf", limit=3)

        assert "offset" in result.lower()

    async def test_403_returns_error(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(
            403, text="Forbidden: invalid app token"
        )
        result = await tools.query_dataset("4jcx-enxf")

        assert "403" in result
        assert "Forbidden" in result


# ===================================================================
# preview_dataset
# ===================================================================


class TestPreviewDataset:
    """Tests for the preview_dataset tool."""

    async def test_successful_preview(self, mock_api):
        mock_api.get(f"{SODA_BASE}/test-id.json").respond(200, json=FAKE_QUERY_ROWS)

        result = await tools.preview_dataset("test-id", limit=3)

        assert "Preview" in result
        assert "species" in result
        assert "Liquidambar" in result

    async def test_400_returns_error_body(self, mock_api):
        mock_api.get(f"{SODA_BASE}/bad-id.json").respond(
            400, text="Dataset not found"
        )
        result = await tools.preview_dataset("bad-id")

        assert "400" in result
        assert "Dataset not found" in result

    async def test_empty_dataset_returns_message(self, mock_api):
        mock_api.get(f"{SODA_BASE}/empty.json").respond(200, json=[])

        result = await tools.preview_dataset("empty")

        assert "No data found" in result

    async def test_empty_dataset_id_returns_error(self, mock_api):
        result = await tools.preview_dataset("")
        assert "Error" in result


# ===================================================================
# get_column_stats
# ===================================================================


class TestGetColumnStats:
    """Tests for the get_column_stats tool."""

    async def test_successful_stats(self, mock_api):
        rows = [
            {"species": "Oak", "count": "45"},
            {"species": "Elm", "count": "30"},
            {"species": "Pine", "count": "25"},
        ]
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(200, json=rows)

        result = await tools.get_column_stats("4jcx-enxf", "species")

        assert "Oak" in result
        assert "45" in result
        assert "Distinct values: 3" in result

    async def test_400_returns_socrata_error_body(self, mock_api):
        mock_api.get(f"{SODA_BASE}/4jcx-enxf.json").respond(
            400, json=SOCRATA_400_LOCATION_ERROR
        )
        result = await tools.get_column_stats("4jcx-enxf", "stname")

        assert "type-mismatch" in result
        assert "stname_address" in result
        assert "get_dataset_info" in result

    async def test_empty_args_return_error(self, mock_api):
        result = await tools.get_column_stats("", "species")
        assert "Error" in result

        result = await tools.get_column_stats("4jcx-enxf", "")
        assert "Error" in result


# ===================================================================
# search_datasets
# ===================================================================


class TestSearchDatasets:
    """Tests for the search_datasets tool."""

    async def test_successful_search(self, mock_api):
        mock_api.get(DISCOVERY_API_BASE).respond(200, json=FAKE_SEARCH_RESULTS)

        result = await tools.search_datasets("trees")

        assert "Street Trees" in result
        assert "4jcx-enxf" in result
        assert "CrimeWatch" in result
        assert "2 dataset(s)" in result

    async def test_no_results(self, mock_api):
        mock_api.get(DISCOVERY_API_BASE).respond(
            200, json={"resultSetSize": 0, "results": []}
        )
        result = await tools.search_datasets("nonexistent")

        assert "No datasets found" in result

    async def test_next_steps_hint(self, mock_api):
        mock_api.get(DISCOVERY_API_BASE).respond(200, json=FAKE_SEARCH_RESULTS)

        result = await tools.search_datasets("trees")

        assert "get_dataset_info" in result


# ===================================================================
# list_categories
# ===================================================================


class TestListCategories:
    """Tests for the list_categories tool."""

    async def test_returns_categories(self, mock_api):
        mock_api.get(DISCOVERY_API_BASE).respond(200, json=FAKE_SEARCH_RESULTS)

        result = await tools.list_categories()

        assert "Environmental" in result
        assert "Public Safety" in result

    async def test_no_categories(self, mock_api):
        empty = {"resultSetSize": 0, "results": []}
        mock_api.get(DISCOVERY_API_BASE).respond(200, json=empty)

        result = await tools.list_categories()

        assert "No categories found" in result
