from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_entry_filter_research import (
    build_entry_filter_research,
    discover_strategy_3_sample,
    load_strategy_2_inputs,
    read_executed_trades,
    write_outputs,
)
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 pre-entry filter diagnostics.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--strategy2-trades-path",
        default="backtests/reports/strategy_2_human_management_intermediate/executed_trades.csv",
    )
    parser.add_argument(
        "--strategy2-entry-quality-dir",
        default="backtests/reports/strategy_2_entry_quality_diagnostics",
    )
    parser.add_argument("--strategy3-trades-path", default="")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_entry_filter_research")
    parser.add_argument("--docs-path", default="docs/research/strategy_2_entry_filter_research.md")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, str]:
    strategy2_trades_path = Path(args.strategy2_trades_path)
    if not strategy2_trades_path.exists():
        raise FileNotFoundError(f"Strategy 2 executed trades file not found: {strategy2_trades_path}")

    strategy2_rows, strategy2_diagnostic_rows, source = load_strategy_2_inputs(
        strategy2_trades_path,
        Path(args.strategy2_entry_quality_dir),
    )
    strategy3_path = Path(args.strategy3_trades_path) if args.strategy3_trades_path else discover_strategy_3_sample(REPO_ROOT)
    strategy3_rows = None
    if strategy3_path is not None and strategy3_path.exists():
        strategy3_rows, strategy3_columns = read_executed_trades(strategy3_path)
        source["strategy3_columns"] = strategy3_columns
    else:
        strategy3_path = None
        source["strategy3_columns"] = []

    source.update(
        {
            "strategy3_source_path": str(strategy3_path) if strategy3_path is not None else None,
            "dry_run": bool(args.dry_run),
            "command": "python scripts/analyze_strategy_2_entry_filter_research.py",
        }
    )

    market_data = load_csv_timeframes(args.symbol, ["M1", "M5", "M15"], data_dir=args.data_dir)
    report = build_entry_filter_research(
        strategy2_executed_rows=strategy2_rows,
        strategy2_diagnostic_rows=strategy2_diagnostic_rows,
        strategy3_rows=strategy3_rows,
        strategy3_source_path=str(strategy3_path) if strategy3_path is not None else None,
        market_data=market_data,
        symbol=args.symbol,
        source=source,
    )
    return write_outputs(report, Path(args.output_dir), Path(args.docs_path))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
