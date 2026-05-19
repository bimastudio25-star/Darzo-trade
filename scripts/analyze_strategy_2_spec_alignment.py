from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analytics.strategy_2_entry_quality_diagnostics import read_executed_trades
from dazro_trade.analytics.strategy_2_spec_alignment_audit import (
    build_spec_alignment_audit,
    load_stats_profile,
    write_audit_outputs,
)
from dazro_trade.backtest.data_loader import load_csv_timeframes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only Strategy 2 spec alignment audit.")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--trades-path", default="backtests/reports/strategy_2_human_management_intermediate/executed_trades.csv")
    parser.add_argument("--stats-summary-path", default="backtests/reports/strategy_2_liquidity_expansion_stats/liquidity_expansion_stats_summary.json")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_2_spec_alignment_audit")
    parser.add_argument("--source-pdf-found", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, str]:
    trades_path = Path(args.trades_path)
    if not trades_path.exists():
        raise FileNotFoundError(f"Strategy 2 executed trades file not found: {trades_path}")
    trades, _ = read_executed_trades(trades_path)
    market_data = load_csv_timeframes(args.symbol, ["M1", "M15", "H1"], data_dir=args.data_dir)
    profile = load_stats_profile(Path(args.stats_summary_path))
    report = build_spec_alignment_audit(
        trades,
        market_data=market_data,
        profile=profile,
        source_path=str(trades_path),
        symbol=args.symbol,
        source_pdf_found=bool(args.source_pdf_found),
    )
    return write_audit_outputs(report, Path(args.output_dir))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run(args)
    print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
