"""Aggregate one or more scored runs into a comparison report.

Usage:
    python -m eval.runner.report \\
        --runs eval/runs/2026-05-04_baseline eval/runs/2026-05-04_codemode \\
        --out eval/runs/report.md

Reads each run's scores.jsonl, groups by (config_name, tier), and writes a
Markdown table comparing accuracy and trajectory metrics across configs.

This is dependency-free (no pandas) so it works on a clean checkout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _safe_mean(xs: list[float | int | None]) -> float | None:
    vals = [x for x in xs if isinstance(x, (int, float))]
    return round(mean(vals), 2) if vals else None


def aggregate(scores: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in scores:
        key = (s["config_name"], s["tier"])
        buckets.setdefault(key, []).append(s)

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in buckets.items():
        out[key] = {
            "n": len(rows),
            "correctness": _safe_mean([r.get("correctness") for r in rows]),
            "groundedness": _safe_mean([r.get("groundedness") for r in rows]),
            "completeness": _safe_mean([r.get("completeness") for r in rows]),
            "tool_call_count": _safe_mean([r.get("tool_call_count") for r in rows]),
            "input_tokens": _safe_mean([r.get("input_tokens") for r in rows]),
            "output_tokens": _safe_mean([r.get("output_tokens") for r in rows]),
            "exhaustion_rate": round(
                sum(1 for r in rows if r.get("exhausted")) / len(rows), 2
            ),
        }
    return out


def overall(scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_config: dict[str, list[dict[str, Any]]] = {}
    for s in scores:
        by_config.setdefault(s["config_name"], []).append(s)
    out = {}
    for cfg, rows in by_config.items():
        out[cfg] = {
            "n": len(rows),
            "correctness": _safe_mean([r.get("correctness") for r in rows]),
            "groundedness": _safe_mean([r.get("groundedness") for r in rows]),
            "completeness": _safe_mean([r.get("completeness") for r in rows]),
            "tool_call_count": _safe_mean([r.get("tool_call_count") for r in rows]),
            "input_tokens": _safe_mean([r.get("input_tokens") for r in rows]),
            "output_tokens": _safe_mean([r.get("output_tokens") for r in rows]),
            "exhaustion_rate": round(
                sum(1 for r in rows if r.get("exhausted")) / len(rows), 2
            ),
        }
    return out


def render(scores: list[dict[str, Any]]) -> str:
    by_tier = aggregate(scores)
    by_overall = overall(scores)

    lines: list[str] = ["# Eval report", ""]

    lines.append("## Overall (all tiers combined)")
    lines.append("")
    lines.append("| Config | n | Correct | Ground | Complete | Tool calls | In tokens | Out tokens | Exhausted |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for cfg, m in sorted(by_overall.items()):
        lines.append(
            f"| {cfg} | {m['n']} | {m['correctness']} | {m['groundedness']} | "
            f"{m['completeness']} | {m['tool_call_count']} | {m['input_tokens']} | "
            f"{m['output_tokens']} | {m['exhaustion_rate']:.0%} |"
        )

    lines.append("")
    lines.append("## By tier")
    lines.append("")
    lines.append("| Config | Tier | n | Correct | Ground | Complete | Tool calls | In tokens | Out tokens | Exhausted |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for (cfg, tier), m in sorted(by_tier.items()):
        lines.append(
            f"| {cfg} | {tier} | {m['n']} | {m['correctness']} | {m['groundedness']} | "
            f"{m['completeness']} | {m['tool_call_count']} | {m['input_tokens']} | "
            f"{m['output_tokens']} | {m['exhaustion_rate']:.0%} |"
        )

    lines.append("")
    lines.append("## Per-question (mean across trials)")
    lines.append("")
    by_q: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in scores:
        by_q.setdefault((s["config_name"], s["question_id"]), []).append(s)
    lines.append("| Config | Question | n | Correct | Ground | Complete | Tool calls | Tokens (in/out) | Exhausted |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for (cfg, qid), rows in sorted(by_q.items()):
        c = _safe_mean([r.get("correctness") for r in rows])
        g = _safe_mean([r.get("groundedness") for r in rows])
        co = _safe_mean([r.get("completeness") for r in rows])
        tc = _safe_mean([r.get("tool_call_count") for r in rows])
        ti = _safe_mean([r.get("input_tokens") for r in rows])
        to = _safe_mean([r.get("output_tokens") for r in rows])
        ex = round(sum(1 for r in rows if r.get("exhausted")) / len(rows), 2)
        lines.append(
            f"| {cfg} | {qid} | {len(rows)} | {c} | {g} | {co} | {tc} | "
            f"{ti}/{to} | {ex:.0%} |"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    all_scores: list[dict[str, Any]] = []
    for r in args.runs:
        scores_path = Path(r) / "scores.jsonl"
        if not scores_path.exists():
            print(f"  [warn] {scores_path} not found — run judge.py first.")
            continue
        for line in scores_path.read_text().splitlines():
            line = line.strip()
            if line:
                all_scores.append(json.loads(line))

    if not all_scores:
        raise SystemExit("No scores to report.")

    out = Path(args.out)
    out.write_text(render(all_scores))
    print(f"Wrote report to {out}")


if __name__ == "__main__":
    main()
