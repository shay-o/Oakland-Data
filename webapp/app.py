"""FastAPI web app providing a chat interface to Oakland's open data."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oakland_mcp import tools

app = FastAPI(title="Oakland Open Data Chat")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")

client: OpenAI | None = None


def get_client() -> OpenAI:
    global client
    if client is None:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    return client


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_datasets",
            "description": (
                "Search Oakland's open data portal for datasets matching keywords. "
                "Use when the user mentions a topic or data type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search for"},
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g., 'Public Safety')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (1-50, default 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "List all dataset categories on Oakland's open data portal.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dataset_info",
            "description": (
                "Get detailed metadata and column schema for a dataset. "
                "Call before query_dataset to learn column names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "Socrata dataset ID (e.g., 'ym6k-rx7a')",
                    },
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_dataset",
            "description": "Get a sample of actual data rows from a dataset with no filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Socrata dataset ID"},
                    "limit": {
                        "type": "integer",
                        "description": "Sample rows (1-50, default 10)",
                        "default": 10,
                    },
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_dataset",
            "description": (
                "Query a dataset with structured SoQL clauses. Call get_dataset_info "
                "first to know valid column names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Socrata dataset ID"},
                    "select": {
                        "type": "string",
                        "description": "Columns/aggregations (e.g., 'crimetype, count(*) as cnt')",
                    },
                    "where": {
                        "type": "string",
                        "description": "Filter (e.g., \"crimetype = 'ROBBERY'\")",
                    },
                    "order": {"type": "string", "description": "Sort (e.g., 'datetime DESC')"},
                    "group": {"type": "string", "description": "Group by columns"},
                    "having": {"type": "string", "description": "Filter on aggregates"},
                    "limit": {"type": "integer", "description": "Max rows (1-5000)", "default": 500},
                    "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_column_stats",
            "description": (
                "Get distinct values and frequency counts for a dataset column. "
                "Useful for understanding what values exist before querying."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Socrata dataset ID"},
                    "column_name": {
                        "type": "string",
                        "description": "Exact column name to analyze",
                    },
                },
                "required": ["dataset_id", "column_name"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "search_datasets": tools.search_datasets,
    "list_categories": tools.list_categories,
    "get_dataset_info": tools.get_dataset_info,
    "preview_dataset": tools.preview_dataset,
    "query_dataset": tools.query_dataset,
    "get_column_stats": tools.get_column_stats,
}

SYSTEM_PROMPT = """You are an Oakland Open Data assistant. You help users explore and analyze 
public government data from Oakland, California's open data portal (data.oaklandca.gov).

You have tools to search for datasets, view metadata, preview data, run queries, and get 
column statistics. Follow this workflow:

1. Search for relevant datasets using search_datasets
2. Get metadata with get_dataset_info to understand columns
3. Preview data or get column stats to understand values
4. Query with specific filters using query_dataset

Always explain what data you found and what it means. If a query returns no results, 
suggest alternative approaches. Be specific about data limitations (e.g., date ranges, 
missing fields).

Keep responses concise but informative. Format data clearly when presenting results."""


async def execute_tool(name: str, args: dict[str, Any]) -> str:
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return f"Unknown tool: {name}"
    try:
        return await func(**args)
    except Exception as e:
        return f"Error executing {name}: {e}"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.post("/api/chat")
async def chat(request: Request):
    """Handle a chat message, executing tool calls as needed."""
    body = await request.json()
    user_message = body.get("message", "")
    conversation_history = body.get("history", [])

    if not OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY not configured. Set it in .env file."}

    openai_client = get_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    all_tool_calls = []

    max_iterations = 10
    for _ in range(max_iterations):
        response = openai_client.chat.completions.create(
            model=MODEL,
            max_tokens=4096,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                result = await execute_tool(tool_name, tool_input)

                all_tool_calls.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result[:500] + "..." if len(result) > 500 else result,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
        else:
            text = choice.message.content or ""

            # Strip system message before returning history to the client
            client_messages = [m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")]
            client_messages.append({"role": "assistant", "content": text})

            return {
                "response": text,
                "tool_calls": all_tool_calls,
                "messages": client_messages,
            }

    return {"error": "Max tool call iterations reached.", "tool_calls": all_tool_calls}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
