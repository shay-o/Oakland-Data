# Oakland MCP eval harness

A small harness for running the Oakland Open Data agent against a fixed test
set under different configs, scoring with an LLM judge, and producing a
comparison report.

The first experiment built into this harness is **baseline vs code-mode** —
the same MCP, exposed as either six structured tools or one `python_eval`
tool. All else (model, prompt principles, loop budget, test set) is held
constant.

## Layout

```
eval/
  README.md                 # this file
  test_sets/
    oakland_eval.jsonl      # 19 questions across 5 tiers
  prompts/
    oakland_baseline.md     # current prompt (six-tool surface)
    oakland_codemode.md     # same principles, one-tool surface
  configs/
    oakland-baseline.yaml
    oakland-codemode.yaml
  runner/
    run_eval.py             # drives the agent loop per config
    judge.py                # LLM-judge scoring of transcripts
    report.py               # markdown comparison report
  runs/                     # output goes here, gitignored if you wish
```

The code-mode side relies on:

- `oakland_mcp/runtime/oakland.py` — the agent-facing API surface (sync, returns dicts).
- `oakland_mcp/runtime/README.md` — the agent-facing playbook (datasets, quirks, examples).
- `oakland_mcp/sandbox.py` — subprocess sandbox for running scripts.
- `tools.py::python_eval` and the `python_eval` tool registered in `server.py`.

## Prerequisites

```bash
export OPENROUTER_API_KEY=sk-or-...
# Optional: keep model and Socrata token in .env
```

`OPENROUTER_API_KEY` is required for both running the agent and the judge.
Both default to `anthropic/claude-sonnet-4`.

## Running the experiment

### 1. Run both configs against the test set

```bash
# Baseline: six structured tools
python -m eval.runner.run_eval \
  --config eval/configs/oakland-baseline.yaml \
  --test-set eval/test_sets/oakland_eval.jsonl \
  --out eval/runs/baseline

# Code mode: one python_eval tool
python -m eval.runner.run_eval \
  --config eval/configs/oakland-codemode.yaml \
  --test-set eval/test_sets/oakland_eval.jsonl \
  --out eval/runs/codemode
```

Each command produces one transcript JSON per (question x trial) plus a
`summary.jsonl` and a copy of the resolved config + prompt.

Useful flags while iterating:
- `--only T1-01,T2-01` — restrict to specific question IDs.
- `--trials 1` — override `trials_per_question` for a quick pass.

### 2. Score the transcripts

```bash
python -m eval.runner.judge \
  --runs eval/runs/baseline \
  --test-set eval/test_sets/oakland_eval.jsonl

python -m eval.runner.judge \
  --runs eval/runs/codemode \
  --test-set eval/test_sets/oakland_eval.jsonl
```

Each writes `scores.jsonl` and `scores.csv` into the runs directory.

### 3. Build the comparison report

```bash
python -m eval.runner.report \
  --runs eval/runs/baseline eval/runs/codemode \
  --out eval/runs/report.md
```

The report contains:
- **Overall** — one row per config, averaged across all questions.
- **By tier** — config × tier (T1-T5).
- **Per-question** — config × question id (mean across trials).

## What the metrics mean

For each transcript the runner records:
- `tool_call_count` — total tool calls across all turns. In code mode each `python_eval` counts as one.
- `input_tokens` / `output_tokens` — sum across the whole conversation. The metric most directly tied to Anthropic's code-execution claim.
- `exhausted` — whether any turn hit the loop budget and triggered the fallback summary. Regression guard for the 225fe44 bug.
- `correctness`, `groundedness`, `completeness` — judge scores 0-3 against the rubric.

What to expect from the comparison:
- Code mode: dramatic drop in tokens and tool-call count on T2/T4/T5; equal-or-better correctness; near-zero exhaustion.
- Baseline: cheaper on T1 single-lookups; higher on multi-step questions.

## Iterating on the MCP

After a first run, the loop is:
1. Read the failing transcripts (low correctness / exhausted / many tool calls).
2. Decide whether the failure is a tool-description issue, a missing-tool issue, an error-message issue, or a prompt issue.
3. Make ONE change.
4. Re-run only the affected questions: `--only T3-01,T3-02 --trials 1`.
5. If it helps, run the full set again with default trials.

Tag run directories so you can A/B over time:
`eval/runs/2026-05-04_baseline-v1`, `eval/runs/2026-05-05_baseline-v2`, etc.

## Caveats

- The in-process baseline calls `oakland_mcp.tools` directly rather than over real MCP stdio. That's deliberate for this first experiment — the variable under test is the tool surface, not the transport. To compare against an external MCP (e.g. srobbin/opengov-mcp-server), add a new transport mode to `run_eval.py`.
- Some questions reference current data ("last 90 days", "this year"). Both configs see the same dates within a run, but absolute scores aren't comparable across months.
- The sandbox is **not a security boundary**. The model-authored script can read your filesystem and make outbound network calls. Fine for personal eval; swap for Vercel Sandbox before exposing to untrusted input.
