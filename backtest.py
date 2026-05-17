from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dazro_trade.backtest import (
    BacktestConfig,
    BacktestInterrupted,
    BacktestPerformanceConfig,
    compute_backtest_metrics,
    export_backtest_reports,
    format_validation_report,
    load_csv_timeframes,
    resolve_strategy_selection,
    run_backtest,
    validate_csv_timeframes,
)
from dazro_trade.analytics.candle_behavior_report import (
    build_report as build_candle_behavior_report,
    iterate_candle_behavior_records,
    write_records_csv as write_candle_behavior_records_csv,
    write_report_files as write_candle_behavior_files,
)
from dazro_trade.analytics.trade_link import link_records_to_trades
from dazro_trade.analytics.trade_linked_edge_report import (
    build_trade_linked_report,
    write_trade_linked_files,
)
from dazro_trade.analytics.zone_features import extract_htf_liquidity_zones
from dazro_trade.backtest.runner import build_equity_curve
from dazro_trade.core.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("backtest")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _parse_lookback(value: str | None, defaults: dict[str, int]) -> dict[str, int]:
    if not value:
        return dict(defaults)
    out = dict(defaults)
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"invalid_lookback_item={item}")
        tf, raw = item.split("=", 1)
        out[tf.strip().upper()] = int(raw.strip())
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dazro_trade backtest runner")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--from", dest="date_from", default=None, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", default=None, help="ISO date (YYYY-MM-DD)")
    parser.add_argument("--timeframes", default="M1,M5,M15,H1,H4,D1")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports")
    parser.add_argument("--driver-timeframe", default="M15")
    parser.add_argument("--max-sim-bars", type=int, default=480)
    parser.add_argument("--strategies", default="all", help="Strategy aliases: adelin, strategy_2_0, liquidity_expansion, all")
    parser.add_argument("--fast", action="store_true", help="Use precomputed no-lookahead slicing with bounded lookback windows")
    parser.add_argument("--max-candles", type=int, default=None, help="Debug cap per evaluator driver")
    parser.add_argument("--progress-every-candles", type=int, default=500)
    parser.add_argument("--lookback", default=None, help="Comma-separated fast lookbacks, e.g. M1=2000,M5=2000,H1=1000")
    parser.add_argument("--liquidity-map-lookback", default=None, help="Comma-separated Adelin liquidity map lookbacks, e.g. H4=300,H1=500,M15=1000,M5=1500")
    parser.add_argument("--validate-only", action="store_true", help="Validate CSVs and exit without running backtest")
    parser.add_argument(
        "--profile-candle-behavior",
        action="store_true",
        help="After the backtest, scan the chosen M1/M5 timeframe and emit profile_candle_behavior.{json,md} with per-candle features + zone-reaction stats. Read-only; does not change live rules.",
    )
    parser.add_argument(
        "--profile-candle-tf",
        default="M5",
        choices=("M1", "M5"),
        help="Timeframe to scan for the candle-behavior profile. Default M5.",
    )
    args = parser.parse_args(argv)

    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    date_from = _parse_date(args.date_from)
    date_to = _parse_date(args.date_to)
    try:
        strategies = resolve_strategy_selection(args.strategies)
        perf_defaults = BacktestPerformanceConfig()
        lookback_by_timeframe = _parse_lookback(args.lookback, perf_defaults.lookback_by_timeframe)
        liquidity_map_lookback = _parse_lookback(args.liquidity_map_lookback, perf_defaults.liquidity_map_lookback_by_timeframe)
    except ValueError as exc:
        log.error("backtest_cli_invalid_arg: %s", exc)
        return 2

    if args.validate_only:
        log.info("validate_only symbol=%s tfs=%s dir=%s", args.symbol, tfs, args.data_dir)
        report = validate_csv_timeframes(args.symbol, tfs, data_dir=args.data_dir)
        text = format_validation_report(report)
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "data_validation.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        (out_dir / "data_validation.txt").write_text(text, encoding="utf-8")
        print(text)
        return 0 if report.ok else 1

    log.info(
        "backtest_start symbol=%s tfs=%s from=%s to=%s strategies=%s fast=%s max_candles=%s",
        args.symbol,
        tfs,
        date_from,
        date_to,
        strategies,
        args.fast,
        args.max_candles,
    )

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
        strategies=strategies,
        performance=BacktestPerformanceConfig(
            progress_every_candles=args.progress_every_candles,
            max_candles=args.max_candles,
            fast_mode=args.fast,
            lookback_by_timeframe=lookback_by_timeframe,
            liquidity_map_lookback_by_timeframe=liquidity_map_lookback,
        ),
    )
    partial = False
    try:
        signals, trades = run_backtest(market_data, config=cfg)
    except BacktestInterrupted as exc:
        partial = True
        signals, trades = exc.signals, exc.trades
        cfg = exc.config
        log.warning("backtest_interrupted_partial_output signals=%s trades=%s", len(signals), len(trades))
    metrics = compute_backtest_metrics(signals, trades)
    equity_curve = build_equity_curve(trades)
    paths = export_backtest_reports(
        output_dir=args.output_dir,
        metrics=metrics,
        signals=signals,
        trades=trades,
        equity_curve=equity_curve,
        strategy_diagnostics=cfg.strategy_diagnostics,
        partial=partial,
    )

    log.info("backtest_summary signals=%s trades=%s win_rate=%.3f profit_factor=%.3f avg_r=%.3f mdd=%.3f",
             metrics.total_signals, metrics.valid_trades, metrics.win_rate, metrics.profit_factor, metrics.average_r, metrics.max_drawdown_r)
    for name, diag in cfg.strategy_diagnostics.items():
        d = diag.to_dict() if hasattr(diag, "to_dict") else dict(diag) if isinstance(diag, dict) else {}
        log.info("diagnostics strategy=%s data=%s", name, d)
    log.info("backtest_reports paths=%s", paths)

    if args.profile_candle_behavior:
        scan_tf = args.profile_candle_tf
        df_scan = market_data.get(scan_tf)
        if df_scan is None or len(df_scan) == 0:
            log.warning("profile_candle_behavior_no_data tf=%s", scan_tf)
        else:
            zones = extract_htf_liquidity_zones(market_data)
            log.info("profile_candle_behavior_start tf=%s candles=%s zones=%s", scan_tf, len(df_scan), len(zones))
            records = iterate_candle_behavior_records(df_scan, zones)
            report = build_candle_behavior_report(records)
            profile_paths = write_candle_behavior_files(output_dir=args.output_dir, report=report)
            tf_minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}.get(scan_tf, 5)
            trade_links = link_records_to_trades(
                records, signals, trades,
                strategy="strategy_1_adelin_scalp",
                timeframe_minutes=tf_minutes,
                link_window_bars=20,
            )
            csv_path = write_candle_behavior_records_csv(
                output_dir=args.output_dir, records=records, trade_links=trade_links,
            )
            edge_report = build_trade_linked_report(records, trade_links)
            edge_paths = write_trade_linked_files(output_dir=args.output_dir, report=edge_report)
            log.info(
                "profile_candle_behavior_written market=%s records_csv=%s edge=%s records=%s linked=%s",
                profile_paths, csv_path, edge_paths, len(records), len(trade_links),
            )

    if partial:
        log.warning("backtest_partial_output_saved paths=%s", paths)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
