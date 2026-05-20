from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_2_visual_review_pack import create_review_pack


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a research-only Strategy 2 manual visual review pack.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--auto-samples-path",
        default="backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv",
        help="Read-only statistical sample recorder output.",
    )
    parser.add_argument(
        "--hypotheses-dir",
        default="backtests/reports/strategy_2_auto_filter_hypothesis_diagnostics",
        help="Read-only auto-filter hypothesis diagnostics directory. Missing CSVs are tolerated.",
    )
    parser.add_argument(
        "--output-dir",
        default="backtests/reports/strategy_2_manual_visual_review_pack",
        help="Output directory for static review HTML, PNGs, and prefilled labels.",
    )
    parser.add_argument("--max-samples", type=int, default=40)
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", default=True, help="Research-only mode; writes review pack files only.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.symbol != "XAUUSD":
        raise ValueError("This review pack is XAUUSD-only for the Strategy 2 research branch.")
    result = create_review_pack(
        symbol=args.symbol,
        data_dir=args.data_dir,
        auto_samples_path=args.auto_samples_path,
        hypotheses_dir=args.hypotheses_dir,
        output_dir=args.output_dir,
        max_samples=args.max_samples,
        pip_factor=args.pip_factor,
        dry_run=args.dry_run,
    )
    return result.to_summary()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

