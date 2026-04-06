# Oakland Data MCP

AI-powered access to Oakland, California's open government data via the Socrata SODA API.

Two ways to use it:
1. **MCP Server** — connect from Claude Desktop, Cursor, or any MCP client
2. **Web Chat** — browser-based chat interface for interactive exploration

## Quick Start

### 1. Install dependencies

```bash
cd Oakland-data-MCP
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — add your OPENROUTER_API_KEY (required for web chat only)
# Get a key at https://openrouter.ai/keys
# SOCRATA_APP_TOKEN is optional but recommended for higher rate limits
```

### 3a. Run as MCP Server (for Claude Desktop / Cursor)

```bash
# Stdio transport (used by MCP clients)
python -m oakland_mcp.server
```

**Cursor setup:** Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "oakland-data": {
      "command": "/path/to/Oakland-data-MCP/.venv/bin/python",
      "args": ["-m", "oakland_mcp.server"]
    }
  }
}
```

**Claude Desktop setup:** Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oakland-data": {
      "command": "/path/to/Oakland-data-MCP/.venv/bin/python",
      "args": ["-m", "oakland_mcp.server"]
    }
  }
}
```

### 3b. Run the Web Chat App

```bash
# Requires OPENROUTER_API_KEY in .env
python webapp/app.py
# Open http://localhost:8000
```

The web app uses [OpenRouter](https://openrouter.ai/) to access LLMs. By default it
uses `anthropic/claude-sonnet-4-20250514`, but you can switch to any model by setting
`OPENROUTER_MODEL` in your `.env` file (e.g., `google/gemini-2.5-pro`, `openai/gpt-4o`).

## Available Tools

| Tool | Description |
|------|-------------|
| `search_datasets` | Search Oakland's catalog by keyword and category |
| `list_categories` | List all dataset categories on the portal |
| `get_dataset_info` | Get metadata, columns, and schema for a dataset |
| `preview_dataset` | Quick sample of actual data rows |
| `query_dataset` | Structured SoQL queries (select, where, order, group) |
| `get_column_stats` | Distinct values and frequency counts for a column |

## Example Queries

- "What crime data does Oakland publish?"
- "Show me the most common 311 complaints this year"
- "What are the top crime types by police beat?"
- "How many street trees does Oakland track?"
- "Show campaign finance contributions over $1000"

## Architecture

See [CLAUDE.md](CLAUDE.md) for the full design document including:
- Why MCP over direct API access
- Tool design rationale
- Prior art reviewed (Boston MCP, official Socrata MCP, community MCP)
- Key Oakland datasets
