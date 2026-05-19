from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_entry_quality_diagnostics import read_executed_trades
from dazro_trade.analytics.strategy_2_trade_forensic_replay import build_trade_forensics, write_outputs
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 trade forensic replay.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--trades-path", default="backtests/reports/strategy_2_human_management_intermediate/executed_trades.csv")
    parser.add_argument("--entry-quality-dir", default="backtests/reports/strategy_2_entry_quality_diagnostics")
    parser.add_argument("--entry-filter-dir", default="backtests/reports/strategy_2_entry_filter_research")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_trade_forensic_replay")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_trade_forensic_replay.md")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, str]:
    trades_path = Path(args.trades_path)
    if not trades_path.exists():
        raise FileNotFoundError(f"Strategy 2 executed trades file not found: {trades_path}")
    rows, _ = read_executed_trades(trades_path)
    market_data = load_csv_timeframes(args.symbol, ["M1", "M5", "M15"], data_dir=args.data_dir)
    report = build_trade_forensics(
        rows,
        market_data=market_data,
        source_path=str(trades_path),
        entry_quality_dir=Path(args.entry_quality_dir),
        entry_filter_dir=Path(args.entry_filter_dir),
        symbol=args.symbol,
    )
    return write_outputs(report, Path(args.output_dir), Path(args.docs_path))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
