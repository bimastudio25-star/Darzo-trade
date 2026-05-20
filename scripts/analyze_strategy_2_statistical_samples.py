from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_2_statistical_samples import (
    StatisticalRecorderConfig,
    build_statistical_sample_report,
    write_statistical_sample_outputs,
)
from dazro_trade.analytics.strategy_2_statistical_sample_audit import write_research_doc
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 statistical sample recorder.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_statistical_sample_recorder")
    parser.add_argument("--from", dest="date_from", default="2026-03-15")
    parser.add_argument("--to", dest="date_to", default="2026-05-14")
    parser.add_argument("--h1-reference-mode", choices=["previous", "dominant", "both"], default="both")
    parser.add_argument("--reaction-window-m5", type=int, default=5)
    parser.add_argument("--min-context-sample", type=int, default=20)
    parser.add_argument("--pip-factor", type=float, default=10.0)
    parser.add_argument("--min-manipulation-price", type=float, default=0.1)
    parser.add_argument("--min-distribution-price", type=float, default=1.0)
    parser.add_argument("--docs-path", default="docs/research/strategy_2_statistical_sample_recorder.md")
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _date_arg(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def run(args: argparse.Namespace) -> dict[str, str | float]:
    start_runtime = time.perf_counter()
    config = StatisticalRecorderConfig(
        symbol=args.symbol,
        pip_factor=args.pip_factor,
        h1_reference_mode=args.h1_reference_mode,
        reaction_window_m5=args.reaction_window_m5,
        min_context_sample=args.min_context_sample,
        min_manipulation_price=args.min_manipulation_price,
        min_distribution_price=args.min_distribution_price,
    )
    market_data = load_csv_timeframes(args.symbol, ["M1", "M5", "M15", "H1"], data_dir=args.data_dir)
    report = build_statistical_sample_report(
        symbol=args.symbol,
        market_data=market_data,
        date_from=_date_arg(args.date_from),
        date_to=_date_arg(args.date_to),
        config=config,
    )
    paths = write_statistical_sample_outputs(report, Path(args.output_dir))
    paths["docs_md"] = write_research_doc(report["summary"], Path(args.docs_path))
    paths["runtime_seconds"] = round(time.perf_counter() - start_runtime, 4)
    return paths


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
