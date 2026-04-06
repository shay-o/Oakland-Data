"""Low-level async client for the Socrata SODA and Discovery APIs."""

from __future__ import annotations

from typing import Any

import httpx

from .config import (
    SOCRATA_DOMAIN,
    SOCRATA_APP_TOKEN,
    DISCOVERY_API_BASE,
    SODA_BASE,
    METADATA_BASE,
    REQUEST_TIMEOUT,
)

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        headers = {"Accept": "application/json"}
        if SOCRATA_APP_TOKEN:
            headers["X-App-Token"] = SOCRATA_APP_TOKEN
        _client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def discovery_search(
    query: str = "",
    category: str = "",
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Search the Socrata Discovery API for datasets on the Oakland domain."""
    client = await get_client()
    params: dict[str, Any] = {
        "domains": SOCRATA_DOMAIN,
        "search_context": SOCRATA_DOMAIN,
        "limit": limit,
        "offset": offset,
    }
    if query:
        params["q"] = query
    if category:
        params["categories"] = category

    resp = await client.get(DISCOVERY_API_BASE, params=params)
    resp.raise_for_status()
    return resp.json()


async def discovery_categories() -> list[dict[str, Any]]:
    """Get category facets from the Discovery API."""
    client = await get_client()
    params = {
        "domains": SOCRATA_DOMAIN,
        "search_context": SOCRATA_DOMAIN,
        "limit": 0,
    }
    resp = await client.get(DISCOVERY_API_BASE, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


async def get_metadata(dataset_id: str) -> dict[str, Any]:
    """Fetch dataset metadata via the SODA views API."""
    client = await get_client()
    resp = await client.get(f"{METADATA_BASE}/{dataset_id}.json")
    resp.raise_for_status()
    return resp.json()


async def soda_query(
    dataset_id: str,
    params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Execute a SODA query against a dataset resource."""
    client = await get_client()
    resp = await client.get(
        f"{SODA_BASE}/{dataset_id}.json",
        params=params or {},
    )
    resp.raise_for_status()
    return resp.json()
