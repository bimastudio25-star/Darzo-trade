from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_entry_quality_diagnostics import (
    build_entry_quality_diagnostic,
    read_executed_trades,
    write_outputs,
)
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 entry-quality diagnostics.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--trades-path", default="backtests/reports/strategy_2_human_management_intermediate/executed_trades.csv")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_entry_quality_diagnostics")
    parser.add_argument("--reaction-window-m5", type=int, default=5)
    parser.add_argument("--docs-path", default="docs/research/strategy_2_entry_quality_diagnostics.md")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, str]:
    trades_path = Path(args.trades_path)
    if not trades_path.exists():
        raise FileNotFoundError(f"executed trades file not found: {trades_path}")
    rows, _ = read_executed_trades(trades_path)
    market_data = load_csv_timeframes(args.symbol, ["M1", "M5", "M15"], data_dir=args.data_dir)
    report = build_entry_quality_diagnostic(
        rows,
        market_data=market_data,
        source_path=str(trades_path),
        symbol=args.symbol,
        reaction_window_m5=args.reaction_window_m5,
    )
    return write_outputs(report, Path(args.output_dir), Path(args.docs_path))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
