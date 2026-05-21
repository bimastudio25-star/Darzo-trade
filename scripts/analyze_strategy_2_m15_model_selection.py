from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_m15_model_selection import build_selection_review, write_selection_outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 M15 model selection review.")
    parser.add_argument("--input-dir", default="backtests/reports/strategy_2_mechanical_spec_correction")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_m15_model_selection_review")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_m15_model_selection_review.md")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Safe report-only mode; still writes review outputs.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    result = build_selection_review(args.input_dir, pip_factor=args.pip_factor)
    paths = write_selection_outputs(result, args.output_dir, docs_path=args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": result.summary["runtime_seconds"],
        "models_loaded": result.summary["models_loaded"],
        "rows_loaded": result.summary["rows_loaded"],
        "scorecard_result": result.summary["scorecard_result"],
        "recommendation": result.summary["recommendation"],
        "tail_risk_per_model": result.summary["tail_risk_per_model"],
        "review_candidates_count": result.summary["review_candidates_count"],
        "verdict_flags": result.summary["verdict_flags"],
        "paths": paths,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

