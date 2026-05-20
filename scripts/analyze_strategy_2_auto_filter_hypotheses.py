from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_auto_filter_hypothesis import run_analysis, write_outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 auto filter hypothesis diagnostics.")
    parser.add_argument(
        "--samples-path",
        default="backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv",
        help="Read-only statistical sample recorder CSV.",
    )
    parser.add_argument(
        "--output-dir",
        default="backtests/reports/strategy_2_auto_filter_hypothesis_diagnostics",
        help="Directory for diagnostic outputs.",
    )
    parser.add_argument("--docs-path", default="docs/research/strategy_2_auto_filter_hypothesis_diagnostics.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Research-only mode. Writes reports only, never signals.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    start = time.perf_counter()
    result = run_analysis(args.samples_path, args.output_dir, pip_factor=args.pip_factor, dry_run=args.dry_run)
    paths = write_outputs(result, Path(args.output_dir), docs_path=Path(args.docs_path))
    runtime_seconds = round(time.perf_counter() - start, 4)
    body_counts = result.summary["body_counts"]
    tail_counts = result.summary["tail_counts"]
    strongest = [
        {
            "hypothesis_id": row["hypothesis_id"],
            "tail_removed_pct": row["tail_removed_pct"],
            "body_removed_pct": row["body_removed_pct"],
            "verdict": row["verdict"],
        }
        for _, row in result.hypotheses.head(5).iterrows()
    ]
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": runtime_seconds,
        "samples_loaded": result.summary["samples_loaded"],
        "valid_samples": result.summary["valid_samples"],
        "body_le_8": body_counts["le_8"],
        "body_le_10": body_counts["le_10"],
        "body_le_12": body_counts["le_12"],
        "tail_gt_12": tail_counts["gt_12"],
        "tail_gt_15": tail_counts["gt_15"],
        "tail_gt_20": tail_counts["gt_20"],
        "top_tail_max_manipulation_usd": result.summary["top_tail_max_manipulation_usd"],
        "strongest_hypotheses": strongest,
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
