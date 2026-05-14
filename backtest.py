from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from dazro_trade.backtest import (
    BacktestConfig,
    compute_backtest_metrics,
    export_backtest_reports,
    load_csv_timeframes,
    run_backtest,
)
from dazro_trade.backtest.runner import build_equity_curve
from dazro_trade.core.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("backtest")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dazro_trade backtest runner")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--from", dest="date_from", default=None, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", default=None, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--timeframes", default="M1,M5,M15,H1,H4,D1")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports")
    parser.add_argument("--driver-timeframe", default="H1")
    parser.add_argument("--max-sim-bars", type=int, default=480)
    args = parser.parse_args(argv)

    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    date_from = _parse_date(args.date_from)
    date_to = _parse_date(args.date_to)

    log.info("backtest_start symbol=%s tfs=%s from=%s to=%s", args.symbol, tfs, date_from, date_to)

    market_data = load_csv_timeframes(
        args.symbol,
        tfs,
        data_dir=args.data_dir,
        date_from=date_from,
        date_to=date_to,
    )
    if not market_data:
        log.error("backtest_no_market_data: nothing to do")
        return 2

    cfg = BacktestConfig(
        symbol=args.symbol,
        timeframes=tfs,
        settings=Settings.from_env(env_file=None),
        driver_timeframe=args.driver_timeframe,
        max_sim_bars=args.max_sim_bars,
    )
    signals, trades = run_backtest(market_data, config=cfg)
    metrics = compute_backtest_metrics(signals, trades)
    equity_curve = build_equity_curve(trades)
    paths = export_backtest_reports(
        output_dir=args.output_dir,
        metrics=metrics,
        signals=signals,
        trades=trades,
        equity_curve=equity_curve,
    )

    log.info("backtest_summary signals=%s trades=%s win_rate=%.3f profit_factor=%.3f avg_r=%.3f mdd=%.3f",
             metrics.total_signals, metrics.valid_trades, metrics.win_rate, metrics.profit_factor, metrics.average_r, metrics.max_drawdown_r)
    log.info("backtest_reports paths=%s", paths)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
