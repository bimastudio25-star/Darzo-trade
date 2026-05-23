from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_5_asymmetric_liquidity_reclaim_2r3r import (
    Strategy5Config,
    scan_strategy_5,
    write_outputs,
)
from dazro_trade.backtest.data_loader import load_csv_timeframes


DEFAULT_OUTPUT_DIR = "backtests/reports/strategy_5_asymmetric_liquidity_reclaim_2r3r_diagnostic"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 5 asymmetric liquidity reclaim diagnostic.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--from", dest="date_from", default=None)
    parser.add_argument("--to", dest="date_to", default=None)
    parser.add_argument("--max-context-candles", type=int, default=900)
    parser.add_argument("--max-forward-candles", type=int, default=32)
    parser.add_argument("--dry-run", action="store_true", default=True)
    return parser.parse_args(argv)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def run(args: argparse.Namespace) -> dict[str, object]:
    started = time.perf_counter()
    if args.symbol != "XAUUSD":
        raise ValueError("Strategy 5 diagnostic is XAUUSD-only")
    market_data = load_csv_timeframes(
        args.symbol,
        ["M15", "H1"],
        data_dir=args.data_dir,
        date_from=_parse_date(args.date_from),
        date_to=_parse_date(args.date_to),
    )
    config = Strategy5Config(
        symbol=args.symbol,
        max_context_candles=args.max_context_candles,
        max_forward_candles=args.max_forward_candles,
    )
    result = scan_strategy_5(market_data, config)
    paths = write_outputs(result, Path(args.output_dir))
    return {
        "paths": paths,
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "summary": result["summary"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
