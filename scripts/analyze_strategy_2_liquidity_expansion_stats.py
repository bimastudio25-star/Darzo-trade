from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_2_liquidity_expansion_stats import build_stats_report, write_stats_outputs
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 liquidity expansion statistics.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--from", dest="date_from", default="2026-03-15")
    parser.add_argument("--to", dest="date_to", default="2026-05-09")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_liquidity_expansion_stats")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _date_arg(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def run(args: argparse.Namespace) -> dict[str, str]:
    date_from = _date_arg(args.date_from)
    date_to = _date_arg(args.date_to)
    market_data = load_csv_timeframes(args.symbol, ["M1", "M15", "H1"], data_dir=args.data_dir)
    report = build_stats_report(
        symbol=args.symbol,
        m1=market_data.get("M1"),
        m15=market_data.get("M15"),
        h1=market_data.get("H1"),
        calibration_from=date_from,
        calibration_to=date_to,
    )
    return write_stats_outputs(report, Path(args.output_dir))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
