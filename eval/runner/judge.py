"""LLM-judge scoring of transcripts against the test-set rubric.

Usage:
    python -m eval.runner.judge \\
        --runs eval/runs/2026-05-04_baseline \\
        --test-set eval/test_sets/oakland_eval.jsonl \\
        --judge-model anthropic/claude-sonnet-4

Reads every transcript JSON in --runs, joins it to its rubric in --test-set
by question id, calls the judge model once per transcript, and writes:

    <runs>/scores.jsonl    one line per transcript: id, trial, scores, notes
    <runs>/scores.csv      same data flat for spreadsheets

Three rubric axes per question (correctness, groundedness, completeness),
each scored 0-3. The judge sees the user turns and the assistant final
answers — NOT the tool-call internals — to score answer quality, not
trajectory. Trajectory metrics (tool-call count, exhaustion, tokens) are
already in the transcript.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

JUDGE_SYSTEM = """\
You are an evaluation judge scoring a conversational AI's answers about
Oakland, California open government data.

You will receive:
  1. The original question (one or more user turns).
  2. The assistant's final answer for each turn.
  3. The expected answer shape and a per-axis rubric.

Score on three axes, each 0-3:
  - correctness: Does the final answer correctly answer the question? Are
    specific numbers/IDs/names plausible and consistent? 3=fully correct,
    2=mostly correct with minor issues, 1=partially correct, 0=wrong/missing.
  - groundedness: Does the answer cite or reflect specific values that come
    from the data, vs. handwaving? 3=specific values throughout, 2=mostly
    grounded, 1=some specifics, 0=vague/no grounding.
  - completeness: Does it fully address what was asked, including any
    multi-turn follow-ups? 3=complete, 2=mostly complete, 1=partial, 0=none.

Return ONLY a JSON object:
{"correctness": <0-3>, "groundedness": <0-3>, "completeness": <0-3>, "notes": "<one sentence>"}
"""


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _build_user_block(question: dict[str, Any], transcript: dict[str, Any]) -> str:
    rubric = question.get("rubric", {})
    answer_shape = question.get("answer_shape", "")
    parts = [
        f"# Question id: {question['id']}",
        f"# Tier: {question['tier']}",
        "",
        "## User turns and assistant answers",
        "",
    ]
    turns = transcript.get("turns", []) or []
    for i, (uq, t) in enumerate(zip(question["turns"], turns), 1):
        parts.append(f"### Turn {i}")
        parts.append(f"USER: {uq['user']}")
        parts.append(f"ASSISTANT: {t.get('final_text', '')}")
        parts.append("")
    if len(turns) < len(question["turns"]):
        parts.append(
            f"(Only {len(turns)} of {len(question['turns'])} turns ran; "
            f"transcript may have errored.)"
        )
    parts.append("## Expected answer shape")
    parts.append(answer_shape or "(not specified)")
    parts.append("")
    parts.append("## Rubric")
    for k, v in rubric.items():
        parts.append(f"- **{k}**: {v}")
    parts.append("")
    parts.append("Return JSON only.")
    return "\n".join(parts)


def judge_one(
    client: OpenAI,
    judge_model: str,
    question: dict[str, Any],
    transcript: dict[str, Any],
) -> dict[str, Any]:
    user_block = _build_user_block(question, transcript)
    resp = client.chat.completions.create(
        model=judge_model,
        max_tokens=600,
        temperature=0.0,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_block},
        ],
    )
    text = resp.choices[0].message.content or ""
    parsed = _json_object_from_text(text) or {}
    for axis in ("correctness", "groundedness", "completeness"):
        v = parsed.get(axis)
        try:
            parsed[axis] = max(0, min(3, int(v)))
        except (TypeError, ValueError):
            parsed[axis] = None
    parsed.setdefault("notes", "")
    parsed["raw"] = text
    return parsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", required=True, help="Directory of transcripts.")
    p.add_argument("--test-set", required=True)
    p.add_argument("--judge-model", default="anthropic/claude-sonnet-4")
    args = p.parse_args()

    runs_dir = Path(args.runs)
    test_set = {
        json.loads(line)["id"]: json.loads(line)
        for line in Path(args.test_set).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        sys.exit("OPENROUTER_API_KEY not set.")
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    transcripts = sorted(runs_dir.glob("*__*__t*.json"))
    if not transcripts:
        sys.exit(f"No transcripts found in {runs_dir}")

    scores: list[dict[str, Any]] = []
    for i, tpath in enumerate(transcripts, 1):
        t = json.loads(tpath.read_text())
        q = test_set.get(t["question_id"])
        if not q:
            print(f"  [skip] {tpath.name}: no rubric for {t['question_id']}")
            continue
        print(f"[{i}/{len(transcripts)}] judging {tpath.name}", flush=True)
        s = judge_one(client, args.judge_model, q, t)
        score_entry = {
            "transcript": tpath.name,
            "question_id": t["question_id"],
            "tier": t["tier"],
            "trial": t["trial"],
            "config_name": t["config_name"],
            "model": t["model"],
            "tool_call_count": sum(len(turn["tool_calls"]) for turn in t.get("turns", [])),
            "exhausted": any(turn.get("exhausted") for turn in t.get("turns", [])),
            "input_tokens": sum(turn.get("input_tokens", 0) for turn in t.get("turns", [])),
            "output_tokens": sum(turn.get("output_tokens", 0) for turn in t.get("turns", [])),
            "correctness": s.get("correctness"),
            "groundedness": s.get("groundedness"),
            "completeness": s.get("completeness"),
            "judge_notes": s.get("notes", ""),
        }
        scores.append(score_entry)

    (runs_dir / "scores.jsonl").write_text(
        "\n".join(json.dumps(s) for s in scores)
    )
    if scores:
        keys = list(scores[0].keys())
        with (runs_dir / "scores.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(scores)
    print(f"\nWrote {len(scores)} scored entries to {runs_dir}/scores.{{jsonl,csv}}")


if __name__ == "__main__":
    main()
