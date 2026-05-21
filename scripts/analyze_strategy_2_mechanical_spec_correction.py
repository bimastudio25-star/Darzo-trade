from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_2_mechanical_spec import (
    MechanicalSpecConfig,
    build_mechanical_spec_report,
    write_mechanical_spec_outputs,
)
from dazro_trade.analytics.strategy_2_mechanical_spec_audit import write_research_doc
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 mechanical spec correction diagnostic.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_mechanical_spec_correction")
    parser.add_argument("--from", dest="date_from", default="2026-03-15")
    parser.add_argument("--to", dest="date_to", default="2026-05-14")
    parser.add_argument("--h1-reference-mode", choices=["previous", "dominant", "both"], default="both")
    parser.add_argument("--m15-filter-model", choices=["containing", "preceding", "approach_window", "all"], default="all")
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--mae-avg-usd", type=float, default=4.6471)
    parser.add_argument("--level-take-pips", type=float, default=1.0)
    parser.add_argument("--reentry-pips", type=float, default=1.0)
    parser.add_argument("--min-distribution-usd", type=float, default=1.0)
    parser.add_argument(
        "--old-samples-path",
        default="backtests/reports/strategy_2_statistical_sample_recorder/h1_liquidity_samples.csv",
        help="Optional old fixed x45 recorder output used only for old-vs-new comparison.",
    )
    parser.add_argument("--docs-path", default="docs/research/strategy_2_mechanical_spec_correction.md")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _date_arg(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.symbol != "XAUUSD":
        raise ValueError("This diagnostic branch is XAUUSD-only.")
    config = MechanicalSpecConfig(
        symbol=args.symbol,
        pip_factor=args.pip_factor,
        h1_reference_mode=args.h1_reference_mode,
        m15_filter_model=args.m15_filter_model,
        mae_avg_usd=args.mae_avg_usd,
        min_distribution_usd=args.min_distribution_usd,
        level_take_pips=args.level_take_pips,
        reentry_pips=args.reentry_pips,
        old_samples_path=args.old_samples_path,
    )
    market_data = load_csv_timeframes(args.symbol, ["M1", "M15", "H1"], data_dir=args.data_dir)
    report = build_mechanical_spec_report(
        symbol=args.symbol,
        market_data=market_data,
        date_from=_date_arg(args.date_from),
        date_to=_date_arg(args.date_to),
        config=config,
    )
    paths = write_mechanical_spec_outputs(report, Path(args.output_dir))
    paths["docs_md"] = write_research_doc(report["summary"], args.docs_path)
    return {
        "dry_run": bool(args.dry_run),
        "runtime_seconds": report["summary"]["runtime_seconds"],
        "h1_contexts_analyzed": report["summary"]["h1_contexts_analyzed"],
        "old_x45_valid_count": report["summary"]["old_x45_valid_count"],
        "per_model": report["summary"]["per_model"],
        "paths": paths,
        "verdict_flags": report["summary"]["verdict_flags"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

