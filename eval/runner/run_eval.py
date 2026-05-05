"""Eval runner — drives the agent loop for one config across the test set.

Usage:
    python -m eval.runner.run_eval \\
        --config eval/configs/oakland-baseline.yaml \\
        --test-set eval/test_sets/oakland_eval.jsonl \\
        --out eval/runs/2026-05-04_baseline

Each (question x trial) produces one JSON transcript file. Multi-turn
questions thread their conversation history through the loop so the
loop-exhaustion regression behaviour is preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI

# Make oakland_mcp importable when invoked as `python -m eval.runner.run_eval`.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oakland_mcp import tools  # noqa: E402

load_dotenv()


# ---------------------------------------------------------------------------
# Tool definitions in OpenAI tool-calling format
# ---------------------------------------------------------------------------

ALL_TOOL_DEFS: dict[str, dict[str, Any]] = {
    "search_datasets": {
        "type": "function",
        "function": {
            "name": "search_datasets",
            "description": "Search Oakland's open data portal for datasets matching keywords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    "list_categories": {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "List dataset categories on Oakland's open data portal.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_dataset_info": {
        "type": "function",
        "function": {
            "name": "get_dataset_info",
            "description": "Metadata + column schema for one dataset. Call before query_dataset.",
            "parameters": {
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}},
                "required": ["dataset_id"],
            },
        },
    },
    "preview_dataset": {
        "type": "function",
        "function": {
            "name": "preview_dataset",
            "description": "Get a sample of rows from a dataset with no filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["dataset_id"],
            },
        },
    },
    "query_dataset": {
        "type": "function",
        "function": {
            "name": "query_dataset",
            "description": "Structured SoQL query. Pass clauses; the server builds the query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "select": {"type": "string"},
                    "where": {"type": "string"},
                    "order": {"type": "string"},
                    "group": {"type": "string"},
                    "having": {"type": "string"},
                    "limit": {"type": "integer", "default": 500},
                    "offset": {"type": "integer", "default": 0},
                },
                "required": ["dataset_id"],
            },
        },
    },
    "get_column_stats": {
        "type": "function",
        "function": {
            "name": "get_column_stats",
            "description": "Distinct values and counts for one column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "column_name": {"type": "string"},
                },
                "required": ["dataset_id", "column_name"],
            },
        },
    },
    "python_eval": {
        "type": "function",
        "function": {
            "name": "python_eval",
            "description": (
                "Run a Python script in a sandbox with `from mcp.oakland import "
                "search_datasets, list_categories, get_dataset_info, preview_dataset, "
                "query_dataset, get_column_stats, OaklandAPIError` available. "
                "Functions return structured data (lists of dicts). Print only what "
                "the user needs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string"},
                    "timeout": {"type": "number", "default": 30.0},
                },
                "required": ["script"],
            },
        },
    },
}

TOOL_FUNCS = {
    "search_datasets": tools.search_datasets,
    "list_categories": tools.list_categories,
    "get_dataset_info": tools.get_dataset_info,
    "preview_dataset": tools.preview_dataset,
    "query_dataset": tools.query_dataset,
    "get_column_stats": tools.get_column_stats,
    "python_eval": tools.python_eval,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    tool: str
    arguments: dict[str, Any]
    result_preview: str         # first ~2000 chars
    result_full_chars: int

@dataclass
class TurnRecord:
    user_message: str
    rounds_used: int
    exhausted: bool
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0

@dataclass
class TranscriptRecord:
    question_id: str
    tier: str
    trial: int
    config_name: str
    model: str
    started_at: str
    turns: list[TurnRecord] = field(default_factory=list)
    error: str | None = None

    def total_tool_calls(self) -> int:
        return sum(len(t.tool_calls) for t in self.turns)

    def any_exhaustion(self) -> bool:
        return any(t.exhausted for t in self.turns)

    def total_input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

async def execute_tool(name: str, args: dict[str, Any]) -> str:
    fn = TOOL_FUNCS.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return await fn(**args)
    except Exception as e:
        return f"Error executing {name}: {e}"


async def run_turn(
    *,
    openai_client: OpenAI,
    model: str,
    max_tokens: int,
    temperature: float,
    tool_defs: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    user_message: str,
    max_rounds: int,
) -> TurnRecord:
    """Run one user turn through the tool-calling loop."""
    turn = TurnRecord(user_message=user_message, rounds_used=0, exhausted=False)
    messages.append({"role": "user", "content": user_message})

    t0 = time.monotonic()
    rounds_used = 0

    for _ in range(max_rounds):
        rounds_used += 1
        resp = openai_client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tool_defs,
            messages=messages,
        )
        choice = resp.choices[0]
        if resp.usage:
            turn.input_tokens += resp.usage.prompt_tokens or 0
            turn.output_tokens += resp.usage.completion_tokens or 0

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message.model_dump(exclude_none=True))
            for tc in choice.message.tool_calls or []:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                result = await execute_tool(name, args)
                turn.tool_calls.append(ToolCallRecord(
                    tool=name,
                    arguments=args,
                    result_preview=result[:2000],
                    result_full_chars=len(result),
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            turn.final_text = choice.message.content or ""
            messages.append({"role": "assistant", "content": turn.final_text})
            turn.rounds_used = rounds_used
            turn.duration_ms = int((time.monotonic() - t0) * 1000)
            return turn

    # Exhausted: ask for a tool-less summary so the user always gets text.
    turn.exhausted = True
    messages.append({
        "role": "user",
        "content": (
            "You have used all available tool-calling rounds. Based on what you "
            "have, provide the best answer you can. Do not attempt more tool calls."
        ),
    })
    fb = openai_client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=temperature, messages=messages,
    )
    if fb.usage:
        turn.input_tokens += fb.usage.prompt_tokens or 0
        turn.output_tokens += fb.usage.completion_tokens or 0
    turn.final_text = fb.choices[0].message.content or ""
    messages.append({"role": "assistant", "content": turn.final_text})
    turn.rounds_used = rounds_used
    turn.duration_ms = int((time.monotonic() - t0) * 1000)
    return turn


async def run_question(
    *,
    question: dict[str, Any],
    config: dict[str, Any],
    system_prompt: str,
    trial: int,
) -> TranscriptRecord:
    transcript = TranscriptRecord(
        question_id=question["id"],
        tier=question["tier"],
        trial=trial,
        config_name=config["name"],
        model=config["model"]["name"],
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        transcript.error = "OPENROUTER_API_KEY not set"
        return transcript

    openai_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    tool_defs = [ALL_TOOL_DEFS[name] for name in config["mcp"]["tools"]]
    max_rounds = int(config["agent"]["max_tool_rounds"])
    rendered_prompt = system_prompt.replace("{MAX_TOOL_ROUNDS}", str(max_rounds))

    messages: list[dict[str, Any]] = [{"role": "system", "content": rendered_prompt}]

    try:
        for turn_spec in question["turns"]:
            turn = await run_turn(
                openai_client=openai_client,
                model=config["model"]["name"],
                max_tokens=int(config["model"].get("max_tokens", 4096)),
                temperature=float(config["model"].get("temperature", 0.0)),
                tool_defs=tool_defs,
                messages=messages,
                user_message=turn_spec["user"],
                max_rounds=max_rounds,
            )
            transcript.turns.append(turn)
    except Exception as e:
        transcript.error = f"{type(e).__name__}: {e}"
    return transcript


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_transcript(out_dir: Path, t: TranscriptRecord) -> Path:
    fname = f"{t.config_name}__{t.question_id}__t{t.trial}.json"
    path = out_dir / fname
    path.write_text(json.dumps(asdict(t), indent=2, default=str))
    return path


def load_test_set(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(json.loads(line))
    return out


def load_config(path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(path.read_text())
    # Resolve relative system_prompt_file relative to the config's directory.
    prompt_rel = cfg["agent"]["system_prompt_file"]
    cfg["_system_prompt_path"] = (path.parent / prompt_rel).resolve()
    return cfg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> None:
    cfg = load_config(Path(args.config))
    system_prompt = Path(cfg["_system_prompt_path"]).read_text()
    questions = load_test_set(Path(args.test_set))
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.resolved.yaml").write_text(yaml.safe_dump({
        k: v for k, v in cfg.items() if not k.startswith("_")
    }))
    (out_dir / "system_prompt.md").write_text(system_prompt)

    trials = int(cfg["runtime"].get("trials_per_question", 1))
    if args.trials is not None:
        trials = int(args.trials)

    summary = []
    total = len(questions) * trials
    done = 0
    for q in questions:
        for trial in range(1, trials + 1):
            done += 1
            print(f"[{done}/{total}] {cfg['name']} :: {q['id']} trial {trial}", flush=True)
            t = await run_question(
                question=q, config=cfg, system_prompt=system_prompt, trial=trial,
            )
            path = write_transcript(out_dir, t)
            summary.append({
                "id": q["id"],
                "tier": q["tier"],
                "trial": trial,
                "transcript": path.name,
                "tool_calls": t.total_tool_calls(),
                "exhausted": t.any_exhaustion(),
                "input_tokens": t.total_input_tokens(),
                "output_tokens": t.total_output_tokens(),
                "error": t.error,
            })
            (out_dir / "summary.jsonl").write_text(
                "\n".join(json.dumps(s) for s in summary)
            )

    print(f"\nDone. {done} transcripts in {out_dir}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--test-set", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--only", help="Comma-separated question IDs to run.")
    p.add_argument("--trials", type=int, help="Override trials_per_question.")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
