"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest
import respx
from oakland_mcp import socrata


@pytest.fixture(autouse=True)
async def _reset_socrata_client():
    """Close the singleton httpx client between tests so respx can intercept cleanly."""
    await socrata.close_client()
    yield
    await socrata.close_client()


@pytest.fixture()
def mock_api():
    """Activate respx to intercept all outgoing httpx requests."""
    with respx.mock(assert_all_called=False) as rsps:
        yield rsps


# ---------------------------------------------------------------------------
# Reusable fake API responses
# ---------------------------------------------------------------------------

FAKE_METADATA_WITH_LOCATION = {
    "name": "Street Trees",
    "description": "All trees maintained by the city.",
    "attribution": "Oakland Public Works",
    "category": "Environmental",
    "rowsUpdatedAt": 1712000000,
    "columns": [
        {"fieldName": "objectid", "dataTypeName": "number"},
        {"fieldName": "species", "dataTypeName": "text", "description": "Tree species name"},
        {"fieldName": "stname", "dataTypeName": "location"},
        {"fieldName": "location_1", "dataTypeName": "location"},
    ],
}

FAKE_METADATA_NO_LOCATION = {
    "name": "CrimeWatch",
    "description": "90-day crime reports.",
    "attribution": "Oakland PD",
    "category": "Public Safety",
    "rowsUpdatedAt": 1712000000,
    "columns": [
        {"fieldName": "crimetype", "dataTypeName": "text"},
        {"fieldName": "datetime", "dataTypeName": "calendar_date"},
        {"fieldName": "address", "dataTypeName": "text"},
    ],
}

FAKE_SEARCH_RESULTS = {
    "resultSetSize": 2,
    "results": [
        {
            "resource": {
                "id": "4jcx-enxf",
                "name": "Street Trees",
                "description": "City-maintained street trees",
                "type": "dataset",
                "updatedAt": "2025-03-01T00:00:00.000Z",
            },
            "classification": {"domain_category": "Environmental"},
        },
        {
            "resource": {
                "id": "ym6k-rx7a",
                "name": "CrimeWatch",
                "description": "90-day crime reports",
                "type": "dataset",
                "updatedAt": "2025-03-15T00:00:00.000Z",
            },
            "classification": {"domain_category": "Public Safety"},
        },
    ],
}

FAKE_QUERY_ROWS = [
    {"species": "Liquidambar styraciflua", "objectid": "1"},
    {"species": "Prunus sp", "objectid": "2"},
    {"species": "Ginkgo biloba", "objectid": "3"},
]

SOCRATA_400_LOCATION_ERROR = {
    "message": (
        "Query coordinator error: query.soql.type-mismatch; "
        "Type mismatch for #LIKE, is location"
    ),
    "errorCode": "query.soql.type-mismatch",
}
