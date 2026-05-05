# Oakland Open Data — Agent Playbook

You are working in a Python sandbox. The Oakland Open Data API is available
as a normal Python module:

```python
from mcp.oakland import (
    search_datasets,
    list_categories,
    get_dataset_info,
    preview_dataset,
    query_dataset,
    get_column_stats,
    OaklandAPIError,
)
```

Write a single Python script per question. Print only what the user needs.
Intermediate results stay in variables — they do **not** flow back into your
context. Use that to your advantage: pull rows, aggregate locally, print a
summary.

---

## Function reference (one line each)

| Function | Returns |
|---|---|
| `search_datasets(query, category=None, limit=10)` | `list[dict]` — each: `id`, `name`, `description`, `category`, `type`, `updated_at`, `total_matches` |
| `list_categories()` | `list[dict]` — each: `category`, `count` |
| `get_dataset_info(dataset_id)` | `dict` — `id`, `name`, `row_count`, `updated_at`, `columns` (list of column dicts), `location_columns` (list of names) |
| `preview_dataset(dataset_id, limit=10)` | `list[dict]` — raw rows |
| `query_dataset(dataset_id, select=, where=, order=, group=, having=, limit=, offset=)` | `list[dict]` — query result rows |
| `get_column_stats(dataset_id, column_name)` | `list[dict]` — each: `value`, `count`, `pct` |

`get_dataset_info` returns each column as `{"name", "type", "description", "is_location", "sub_columns"}`. Use `type` and `is_location` to plan your query.

All functions raise `OaklandAPIError` on upstream failure. The exception
message contains the Socrata error body and a recovery hint when applicable.
Do not catch it unless you want to handle the error — let it crash and read
the traceback in stderr; that's enough to fix the next attempt.

---

## High-value datasets

| Dataset | ID | Use for |
|---|---|---|
| CrimeWatch (90 days) | `ym6k-rx7a` | Recent crime questions. Faster than full history. |
| CrimeWatch (full history) | `ppgh-7dqv` | Historical / multi-year crime questions only. |
| 311 Service Requests | `quth-gb8e` | Resident-reported issues: potholes, illegal dumping, graffiti, noise. |
| Street Trees | `4jcx-enxf` | Trees, species, plantings. Filter by location sub-columns, not `stname`. |
| Police Response Times | `wgvi-qsey` | Response time analysis, by priority/beat. |
| Voter Turnout | `nbu9-5uvp` | Civic engagement, turnout by precinct/district. |
| Campaign Finance | `3xq4-ermg` | Contributors, dollar amounts. |
| Public Works Requests | `j4xf-2t25` | Infrastructure work orders. |

If you don't see a fit, call `search_datasets(query)`. If you don't know what
exists at all, call `list_categories()` first.

---

## Quirks you must know

### `location`-type columns can't be filtered with `LIKE` or `=`

A `location` column (e.g. `tree_location`, `incident_location`) is a composite
JSON value: `{address, city, state, zip, latitude, longitude}`. Filtering it
directly returns a Socrata `type-mismatch for #LIKE` error.

**Wrong:**
```python
query_dataset("4jcx-enxf", where="stname LIKE '%PARK%'")  # 400 error
```

**Right:** use a sub-column.
```python
query_dataset("4jcx-enxf", where="stname_address LIKE '%PARK%'")
```

`get_dataset_info(dataset_id)["location_columns"]` lists every location
column in a dataset. Each entry in `["columns"]` includes `is_location: bool`
and `sub_columns: [...]` so you can pick the right one.

### Date columns are ISO strings

```python
query_dataset("quth-gb8e", where="datetime > '2025-01-01T00:00:00'")
```

No timezone suffix. Use `<`, `>`, `between`. For full-year filters:
```python
where="datetime >= '2024-01-01' AND datetime < '2025-01-01'"
```

### Aggregations need an alias to be sortable

```python
query_dataset(
    "ym6k-rx7a",
    select="crimetype, count(*) as cnt",
    group="crimetype",
    order="cnt DESC",   # use the alias, not count(*)
    limit=10,
)
```

Counts come back as **strings**, not ints. Cast with `int(r["cnt"])` if you
need to do arithmetic.

### Aggregate server-side, not in Python

A SoQL `group`/`count`/`sum` query returns 10 rows. Pulling raw rows and
aggregating with a `for` loop returns 50,000 and is slow. Always prefer
server-side aggregation when the question is "how many" / "top N" / "average".

---

## Worked examples

### Top-10 crime types (single query)

```python
from mcp.oakland import query_dataset

rows = query_dataset(
    "ym6k-rx7a",
    select="crimetype, count(*) as cnt",
    group="crimetype",
    order="cnt DESC",
    limit=10,
)
for r in rows:
    print(f"{r['crimetype']}: {r['cnt']}")
```

### Trees on a specific street (location sub-column)

```python
from mcp.oakland import query_dataset

rows = query_dataset(
    "4jcx-enxf",
    select="count(*) as cnt",
    where="stname_address LIKE '%PARK BLVD%'",
)
print(f"Trees on Park Blvd: {rows[0]['cnt']}")
```

### Cross-dataset comparison (two queries, local arithmetic)

```python
from mcp.oakland import query_dataset

start, end = "2024-01-01", "2025-01-01"

req = query_dataset("quth-gb8e", select="count(*) as cnt",
                    where=f"datetime >= '{start}' AND datetime < '{end}'")
crime = query_dataset("ym6k-rx7a", select="count(*) as cnt",
                      where=f"datetime >= '{start}' AND datetime < '{end}'")

n_req, n_crime = int(req[0]['cnt']), int(crime[0]['cnt'])
print(f"311 requests in 2024: {n_req:,}")
print(f"Crimes in 2024: {n_crime:,}")
print(f"Ratio (311 / crime): {n_req / n_crime:.2f}")
```

### Discover an unfamiliar dataset before querying

```python
from mcp.oakland import search_datasets, get_dataset_info

hits = search_datasets("housing")
top = hits[0]
print(f"Using dataset {top['id']}: {top['name']}")

info = get_dataset_info(top['id'])
print(f"  rows: {info['row_count']}, columns: {len(info['columns'])}")
for c in info["columns"][:8]:
    print(f"    {c['name']} ({c['type']})")
```

---

## Workflow guidance

1. **Already know the dataset id and the column?** Skip discovery. Go straight
   to `query_dataset`.
2. **Don't know the column types?** One `get_dataset_info` call. Read the
   columns list once; reuse for the rest of the script.
3. **Don't know what values exist in a column?** `get_column_stats` gives you
   the top 50 with counts in one call.
4. **The first query failed?** Read the exception message. If it mentions
   `location` or `type-mismatch`, switch to the right sub-column.
5. **Need exact numbers?** Aggregate in SoQL. Don't pull rows and count.

Print clearly. Use f-strings. The user only sees what you `print`.
