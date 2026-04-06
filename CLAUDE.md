# Oakland Data MCP

## Project Overview

An MCP (Model Context Protocol) server that provides AI-powered access to Oakland, California's
public government data via the Socrata SODA API. Includes a web chat interface for interactive use.

## Architecture Decision: MCP Server wrapping Socrata SODA API

### Why MCP over direct API access?

We evaluated two approaches for letting AI access Oakland's open data:

1. **MCP Server** — the LLM calls structured tools with typed parameters; the server handles
   API construction, execution, error handling, and response formatting.
2. **Direct API Access** — the LLM reads Socrata API docs and constructs raw SODA/SoQL queries.

We chose MCP because:

- **Reliability**: LLMs are very good at filling in structured tool parameters (pick a tool,
  fill in fields). They are less reliable at generating syntactically correct SoQL queries.
- **Abstraction**: A single MCP tool can hide multi-step complexity (fetch schema, validate
  field names, construct query, paginate, format results).
- **Safety**: The server controls what API calls get made. No risk of malformed queries,
  injection, or runaway pagination.
- **Composability**: MCP tools work with any MCP-compatible client (Claude Desktop, Cursor,
  custom apps). The same tools power both the MCP server and the web app.

The tradeoff is flexibility — MCP tools only expose what we've defined. We mitigate this by
including a general-purpose `query_dataset` tool that accepts structured SoQL clauses
(select, where, order, group, having) so the LLM can construct arbitrary queries without
writing raw query strings.

### Data source: Oakland's Socrata Portal

Oakland runs its open data portal on Socrata (Tyler Data & Insights) at `data.oaklandca.gov`.

Key APIs used:
- **Discovery API**: `api.us.socrata.com/api/catalog/v1` — dataset search and catalog
- **Metadata API**: `data.oaklandca.gov/api/views/{id}.json` — dataset details
- **SODA API**: `data.oaklandca.gov/resource/{id}.json` — data queries via SoQL

### Prior art reviewed

Three existing implementations informed the tool design:

1. **Boston MCP Server** (Python, CKAN-based) — 5 tools with explicit step-by-step workflow
   guidance, field name auto-correction, client-side date filtering. Heavy logging.
   Repo: `/Users/jamesoreilly/Documents/Projects/Boston-Data-MCP/`

2. **Official Socrata MCP** (`socrata/odp-mcp`, TypeScript) — 4 tools, structured SoQL
   builder (server constructs `$query` from individual clauses), any-domain, rate limiting.

3. **Community Socrata MCP** (`srobbin/opengov-mcp-server`, TypeScript) — 1 unified tool
   with 7 operation types. Simpler for LLM but uses raw SoQL for data access.

## Tool Design

Six tools, designed to support a natural discovery-to-query workflow:

### 1. `search_datasets(query, category?, limit?)`
Search Oakland's catalog by keyword, optionally filtered by category.
- **API**: Socrata Discovery API
- **Rationale**: Entry point for every conversation. User says "find crime data" →
  this returns matching datasets with IDs.

### 2. `list_categories()`
List all dataset categories available on Oakland's portal.
- **API**: Discovery API with category facets
- **Rationale**: Helps users who don't know what to search for. "What data does Oakland
  publish?" Missing from Boston's server but present in community server.

### 3. `get_dataset_info(dataset_id)`
Get full metadata: description, columns with types, row count, update frequency, attribution.
- **API**: SODA Metadata endpoint `/api/views/{id}.json`
- **Rationale**: Bridges discovery to querying. Combines Boston's `get_dataset_info` +
  `get_datastore_schema` into one call since Socrata returns both in metadata.

### 4. `preview_dataset(dataset_id, limit?)`
Quick sample of actual data rows with no filtering.
- **API**: SODA `/resource/{id}.json?$limit=N`
- **Rationale**: From official Socrata MCP. Lets LLM/user see what data looks like before
  writing complex queries. Boston doesn't have this — it's a significant gap.

### 5. `query_dataset(dataset_id, select?, where?, order?, group?, having?, limit?, offset?)`
Structured SoQL query. Server constructs `$query` from individual typed clauses.
- **API**: SODA `/resource/{id}.json` with SoQL parameters
- **Rationale**: Core data access. Following official Socrata MCP's design of structured
  clauses is the biggest reliability win over raw SoQL. The LLM fills in
  `where="crimetype = 'ROBBERY'"` rather than constructing a full URL.

### 6. `get_column_stats(dataset_id, column_name)`
Get distinct values, counts, or min/max for a specific column.
- **API**: SODA with `$select=distinct(col)` or `$select=col, count(*) ... $group=col`
- **Rationale**: Novel tool not in any prior implementation. When user asks "what types of
  crime are there?" the LLM currently must query all rows and deduplicate. This makes
  it a single targeted call.

### Typical workflow

```
User: "What are the most common types of crime in Oakland?"

1. search_datasets("crime")                      → finds CrimeWatch dataset (ym6k-rx7a)
2. get_dataset_info("ym6k-rx7a")                 → sees columns: crimetype, description, datetime...
3. get_column_stats("ym6k-rx7a", "crimetype")    → sees distinct crime types with counts
4. query_dataset("ym6k-rx7a",
     select="crimetype, count(*) as cnt",
     group="crimetype",
     order="cnt DESC",
     limit=10)                                    → gets ranked results
```

## Project Structure

```
Oakland-data-MCP/
├── CLAUDE.md                  # This file — plan, reasoning, architecture
├── README.md                  # Setup and usage instructions
├── pyproject.toml             # Python project config and dependencies
├── .env.example               # Environment variables template
├── .gitignore
├── oakland_mcp/
│   ├── __init__.py
│   ├── config.py              # Configuration (env vars, constants)
│   ├── socrata.py             # Low-level Socrata API client (httpx)
│   ├── tools.py               # Tool implementations (pure async functions)
│   └── server.py              # MCP server entry point (FastMCP)
├── webapp/
│   ├── app.py                 # FastAPI backend + Claude API integration
│   └── static/
│       └── index.html         # Single-page chat UI
└── .cursor/
    └── mcp.json               # Cursor MCP client configuration
```

### Key design decisions

- **Shared tool functions**: `tools.py` contains pure async functions that both the MCP
  server and web app import. No code duplication.
- **Async httpx**: All API calls are async for performance. Connection pooling and
  timeouts handled in `socrata.py`.
- **FastMCP**: Uses the Python MCP SDK's FastMCP API for minimal boilerplate.
- **Vanilla frontend**: The web chat UI uses plain HTML/CSS/JS — no build step, no
  framework dependencies. Modern and clean.

## Key Oakland Datasets

High-value datasets identified from the catalog (by page views):

| Dataset | ID | Category | Monthly Views |
|---|---|---|---|
| CrimeWatch Maps (90 days) | `ym6k-rx7a` | Public Safety | 1,546 |
| 311 Service Requests | `quth-gb8e` | Infrastructure | 304 |
| CrimeWatch Data (full) | `ppgh-7dqv` | Public Safety | 1,025 |
| Street Trees | `4jcx-enxf` | Environmental | — |
| Campaign Finance | `3xq4-ermg` | City Government | — |
| Police Response Times | `wgvi-qsey` | Equity | — |
| Voter Turnout | `nbu9-5uvp` | Equity | — |
| Public Works Requests | `j4xf-2t25` | Infrastructure | — |

## Configuration

- `SOCRATA_DOMAIN`: Oakland's Socrata domain (default: `data.oaklandca.gov`)
- `SOCRATA_APP_TOKEN`: Optional app token for higher rate limits
- `OPENROUTER_API_KEY`: Required for the web app (via OpenRouter)
- `OPENROUTER_MODEL`: Optional model override (default: `anthropic/claude-sonnet-4`)

The web app uses OpenRouter (openrouter.ai) rather than calling LLM providers directly.
This provides a single API key for access to models from Anthropic, OpenAI, Google, and
others, and makes it easy to switch models without code changes.
