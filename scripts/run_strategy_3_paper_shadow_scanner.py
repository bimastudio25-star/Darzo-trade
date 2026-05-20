from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.analysis.strategy_3_vwap_1r import Strategy3Diagnostics, evaluate_strategy_3_vwap_1r
from dazro_trade.backtest.data_loader import BacktestDataSlicer, load_csv_timeframes
from dazro_trade.runtime.sessions import current_session_name
from scripts.strategy_3_htf_freshness import analyze_htf_freshness, write_h4_quarantine_report

STRATEGY_NAME = "strategy_3_vwap_1r"
MODE = "paper_shadow"
REQUIRED_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
SAFETY_FLAGS = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_called": False,
    "telegram_sent": False,
    "order_sent": False,
}
CSV_FIELDS = [
    "scanner_run_id",
    "generated_at",
    "signal_timestamp",
    "symbol",
    "strategy",
    "mode",
    "dry_run",
    "cooldown_minutes",
    "direction",
    "entry_price",
    "stop_loss",
    "take_profit",
    "risk_distance",
    "expected_R",
    "setup_mode",
    "band_touched",
    "reason_codes",
    "score",
    "vwap_value",
    "sigma_1_upper",
    "sigma_1_lower",
    "sigma_2_upper",
    "sigma_2_lower",
    "distance_to_vwap",
    "distance_to_band",
    "current_price",
    "session",
    "timeframe",
    "source_timeframe",
    "latest_data_timestamp",
    "data_rows_used",
    "cooldown_status",
    "cooldown_accepted",
    "cooldown_blocked",
    "cooldown_block_reason",
    "last_signal_timestamp_same_symbol_direction",
    "order_sent",
    "telegram_sent",
    "broker_called",
    "live_trading_enabled",
    "order_execution_enabled",
    "telegram_enabled",
]


@dataclass(frozen=True)
class ShadowScannerConfig:
    symbol: str
    timeframes: list[str]
    data_dir: str
    output_dir: Path
    cooldown_minutes: int
    dry_run: bool
    scan_driver_bars: int = 1
    incremental: bool = False
    state_file: Path | None = None
    from_timestamp: str | None = None
    reset_state: bool = False
    append: bool = True
    max_candles_per_run: int | None = None
    enforce_htf_freshness: bool = True
    htf_report_dir: Path | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy 3 paper-only shadow scanner")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframes", default=",".join(REQUIRED_TIMEFRAMES))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_paper_shadow_scanner")
    parser.add_argument("--cooldown-minutes", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--incremental", action="store_true", default=False)
    parser.add_argument("--state-file", default=None)
    parser.add_argument("--from-timestamp", default=None)
    parser.add_argument("--reset-state", action="store_true", default=False)
    parser.add_argument("--append", action="store_true", default=True)
    parser.add_argument("--max-candles-per-run", type=int, default=None)
    parser.add_argument("--allow-stale-htf-context", action="store_true", default=False)
    parser.add_argument("--htf-report-dir", default="backtests/reports/strategy_3_h4_quarantine_diagnostic")
    parser.add_argument(
        "--scan-driver-bars",
        type=int,
        default=1,
        help="Latest M15 driver candles to inspect. Default 1 keeps this runtime-like.",
    )
    return parser.parse_args(argv)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _frame_bounds(market_data: dict[str, pd.DataFrame]) -> tuple[dict[str, str | None], dict[str, str | None]]:
    earliest: dict[str, str | None] = {}
    latest: dict[str, str | None] = {}
    for tf in REQUIRED_TIMEFRAMES:
        frame = market_data.get(tf, pd.DataFrame())
        if frame.empty or "time" not in frame.columns:
            earliest[tf] = None
            latest[tf] = None
            continue
        times = pd.to_datetime(frame["time"], utc=True, errors="coerce").dropna()
        earliest[tf] = _iso(times.min()) if not times.empty else None
        latest[tf] = _iso(times.max()) if not times.empty else None
    return earliest, latest


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _parse_utc(value: Any) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _signal_key(row: dict[str, Any]) -> str:
    return "|".join(
        str(row.get(field) or "")
        for field in ("symbol", "strategy", "signal_timestamp", "direction", "setup_mode", "band_touched")
    )


def _load_existing_signal_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _signal_to_row(
    *,
    scanner_run_id: str,
    generated_at: str,
    symbol: str,
    when: datetime,
    signal: Any,
    session: str,
    cooldown_minutes: int,
    cooldown_status: str,
    cooldown_accepted: bool,
    cooldown_block_reason: str | None,
    last_signal_timestamp: datetime | None,
    latest_by_timeframe: dict[str, str | None],
    data_rows_used: dict[str, int],
) -> dict[str, Any]:
    vwap = signal.confluences.get("vwap") if isinstance(signal.confluences, dict) else {}
    risk_distance = abs(float(signal.entry) - float(signal.stop))
    return {
        "scanner_run_id": scanner_run_id,
        "generated_at": generated_at,
        "signal_timestamp": when.isoformat(),
        "symbol": symbol,
        "strategy": STRATEGY_NAME,
        "mode": MODE,
        "dry_run": True,
        "cooldown_minutes": cooldown_minutes,
        "direction": signal.direction,
        "entry_price": float(signal.entry),
        "stop_loss": float(signal.stop),
        "take_profit": float(signal.tp1),
        "risk_distance": risk_distance,
        "expected_R": float(signal.rr_tp1),
        "setup_mode": signal.setup_mode,
        "band_touched": signal.band_touched,
        "reason_codes": _json_dump(list(signal.reason_codes)),
        "score": None,
        "vwap_value": vwap.get("vwap") if isinstance(vwap, dict) else None,
        "sigma_1_upper": vwap.get("upper_1") if isinstance(vwap, dict) else None,
        "sigma_1_lower": vwap.get("lower_1") if isinstance(vwap, dict) else None,
        "sigma_2_upper": vwap.get("upper_2") if isinstance(vwap, dict) else None,
        "sigma_2_lower": vwap.get("lower_2") if isinstance(vwap, dict) else None,
        "distance_to_vwap": signal.vwap_distance_pips,
        "distance_to_band": signal.vwap_distance_pips,
        "current_price": float(signal.entry),
        "session": session,
        "timeframe": "M15",
        "source_timeframe": "M15",
        "latest_data_timestamp": latest_by_timeframe.get("M15"),
        "data_rows_used": _json_dump(data_rows_used),
        "cooldown_status": cooldown_status,
        "cooldown_accepted": cooldown_accepted,
        "cooldown_blocked": not cooldown_accepted,
        "cooldown_block_reason": cooldown_block_reason,
        "last_signal_timestamp_same_symbol_direction": last_signal_timestamp.isoformat() if last_signal_timestamp else None,
        **SAFETY_FLAGS,
    }


def _write_outputs(
    *,
    output_dir: Path,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "paper_signals.csv"
    jsonl_path = output_dir / "paper_signals.jsonl"
    summary_path = output_dir / "scanner_summary.json"
    md_path = output_dir / "scanner_run.md"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in CSV_FIELDS})

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")

    if rows:
        signal_lines = "\n".join(
            f"- {row['signal_timestamp']} {row['direction']} {row['setup_mode']} {row['band_touched']} "
            f"cooldown={row['cooldown_status']}"
            for row in rows
        )
    else:
        signal_lines = "- no paper signal detected"
    md_path.write_text(
        "\n".join(
            [
                "# Strategy 3 Paper Shadow Scanner Run",
                "",
                "This is paper/shadow output only. No live trading, Telegram signal, broker call, or order was enabled.",
                "",
                f"- scanner_run_id: `{summary['scanner_run_id']}`",
                f"- symbol: `{summary['symbol']}`",
                f"- strategy: `{summary['strategy']}`",
                f"- dry_run: `{summary['dry_run']}`",
                f"- cooldown_minutes: `{summary['cooldown_minutes']}`",
                f"- signals_detected: `{summary['signals_detected']}`",
                f"- signals_accepted: `{summary['signals_accepted']}`",
                f"- signals_blocked_by_cooldown: `{summary['signals_blocked_by_cooldown']}`",
                f"- no_signal_reason: `{summary.get('no_signal_reason')}`",
                "",
                "## Signals",
                "",
                signal_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True, default=str), encoding="utf-8")


def run_scanner(config: ShadowScannerConfig) -> dict[str, Any]:
    if not config.dry_run:
        raise ValueError("paper_shadow_scanner_requires_dry_run")
    if config.symbol != "XAUUSD":
        raise ValueError("paper_shadow_scanner_xauusd_only")
    if config.cooldown_minutes != 120:
        raise ValueError("paper_shadow_scanner_cooldown_must_be_120")

    started_perf = perf_counter()
    run_started_at = _utc_now_iso()
    scanner_run_id = f"strategy3-shadow-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"

    market_data = load_csv_timeframes(config.symbol, config.timeframes, data_dir=config.data_dir)
    missing = [tf for tf in REQUIRED_TIMEFRAMES if tf not in market_data or market_data[tf].empty]
    if missing:
        raise ValueError(f"missing_required_timeframes={missing}")
    earliest_by_tf, latest_by_tf = _frame_bounds(market_data)
    slicer = BacktestDataSlicer(
        market_data,
        fast_mode=True,
        lookback_by_timeframe={"M1": 2000, "M5": 2000, "M15": 1000, "H1": 1000, "H4": 500, "D1": 500},
    )
    driver = slicer.frame("M15")
    if driver.empty:
        raise ValueError("missing_m15_driver_data")
    driver_series = pd.to_datetime(driver["time"], utc=True).dropna()
    state_path = config.state_file or (config.output_dir / "scanner_state.json")
    previous_state = {} if config.reset_state else _read_json(state_path)
    previous_last_processed: str | None = None
    if config.incremental:
        if config.from_timestamp:
            previous_last_processed = _parse_utc(config.from_timestamp).isoformat()
        elif previous_state.get("last_processed_timestamp"):
            previous_last_processed = str(previous_state["last_processed_timestamp"])
        else:
            prior_summary = _read_json(config.output_dir / "scanner_summary.json")
            if prior_summary.get("latest_data_timestamp"):
                previous_last_processed = str(prior_summary["latest_data_timestamp"])
            else:
                raise ValueError("incremental_scanner_requires_state_or_from_timestamp")
        cutoff = _parse_utc(previous_last_processed)
        driver_times = [ts.to_pydatetime() for ts in driver_series[driver_series > pd.Timestamp(cutoff)]]
        if config.max_candles_per_run is not None:
            driver_times = driver_times[: max(0, int(config.max_candles_per_run))]
    else:
        driver_times = [ts.to_pydatetime() for ts in driver_series.tail(max(1, config.scan_driver_bars))]

    htf_diagnostic: dict[str, Any] = {}
    if config.enforce_htf_freshness:
        htf_now = driver_series.max().to_pydatetime()
        htf_diagnostic = analyze_htf_freshness(
            data_dir=Path(config.data_dir),
            symbol=config.symbol,
            market_data=market_data,
            now_utc=htf_now,
        )
        report_dir = config.htf_report_dir or (config.output_dir / "htf_freshness")
        write_h4_quarantine_report(htf_diagnostic, report_dir)
        if htf_diagnostic.get("scanner_blocked_due_to_stale_htf"):
            existing_rows = _load_existing_signal_rows(config.output_dir / "paper_signals.csv") if config.incremental and config.append else []
            runtime_seconds = round(perf_counter() - started_perf, 4)
            summary = {
                "scanner_run_id": scanner_run_id,
                "mode": "paper_shadow_incremental" if config.incremental else MODE,
                "incremental": config.incremental,
                "state_file": str(state_path) if config.incremental else None,
                "previous_last_processed_timestamp": previous_last_processed,
                "new_last_processed_timestamp": previous_last_processed,
                "run_started_at": run_started_at,
                "run_finished_at": _utc_now_iso(),
                "runtime_seconds": runtime_seconds,
                "symbol": config.symbol,
                "strategy": STRATEGY_NAME,
                "data_dir": config.data_dir,
                "output_dir": str(config.output_dir),
                "dry_run": config.dry_run,
                "cooldown_minutes": config.cooldown_minutes,
                "timeframes": list(config.timeframes),
                "latest_available_timestamp_by_timeframe": latest_by_tf,
                "earliest_available_timestamp_by_timeframe": earliest_by_tf,
                "latest_data_timestamp": latest_by_tf.get("M15"),
                "driver_timeframe": "M15",
                "driver_candles_seen": int(len(driver_times)),
                "driver_candles_processed": 0,
                "signals_detected": 0,
                "signals_accepted": 0,
                "signals_blocked_by_cooldown": 0,
                "paper_signals_total_after_run": len(existing_rows),
                "new_paper_signals_this_run": 0,
                "duplicates_skipped": 0,
                "long_signals": 0,
                "short_signals": 0,
                "setup_mode_counts": {},
                "band_touched_counts": {},
                "no_signal_reason": "stale_htf_context_h4",
                "verdict_flags": ["STRATEGY_3_SCANNER_BLOCKED_STALE_HTF_CONTEXT"],
                "htf_freshness": htf_diagnostic,
                "htf_freshness_status": htf_diagnostic.get("htf_freshness_status"),
                "stale_timeframes": htf_diagnostic.get("stale_timeframes", []),
                "scanner_blocked_due_to_stale_htf": True,
                "stale_timeframe": "H4",
                "stale_by_bars": htf_diagnostic.get("h4_stale_by_bars"),
                "latest_h4_timestamp": htf_diagnostic.get("h4_latest_existing_timestamp"),
                "expected_latest_h4_timestamp": htf_diagnostic.get("h4_expected_latest_closed_timestamp"),
                "paper_signals_clean_for_validation": False,
                "safety": dict(SAFETY_FLAGS),
            }
            _write_outputs(output_dir=config.output_dir, rows=existing_rows, summary=summary)
            return summary

    diagnostics = Strategy3Diagnostics()
    diagnostics.cooldown_enabled = config.cooldown_minutes > 0
    diagnostics.strategy_3_cooldown_minutes = config.cooldown_minutes
    last_accepted_by_key: dict[tuple[str, str], datetime] = {}
    if config.incremental and isinstance(previous_state.get("cooldown_state"), dict):
        for raw_key, raw_ts in previous_state["cooldown_state"].items():
            parts = str(raw_key).split("|", 1)
            if len(parts) == 2:
                last_accepted_by_key[(parts[0], parts[1])] = _parse_utc(raw_ts)
    rows: list[dict[str, Any]] = []
    setup_mode_counts: dict[str, int] = {}
    band_touched_counts: dict[str, int] = {}
    long_signals = 0
    short_signals = 0
    blocked = 0
    accepted = 0

    for ts in driver_times:
        when = _parse_utc(ts)
        market_slice = slicer.slice_up_to(when)
        session = current_session_name(when)
        signal = evaluate_strategy_3_vwap_1r(
            market_slice,
            symbol=config.symbol,
            now_utc=when,
            diagnostics=diagnostics,
        )
        if signal is None:
            continue
        key = (config.symbol, signal.direction)
        last_ts = last_accepted_by_key.get(key)
        cooldown_accept = last_ts is None or when - last_ts >= timedelta(minutes=config.cooldown_minutes)
        reason = None if cooldown_accept else "STRATEGY_3_COOLDOWN_BLOCKED"
        if cooldown_accept:
            accepted += 1
            last_accepted_by_key[key] = when
            cooldown_status = "accepted"
        else:
            blocked += 1
            cooldown_status = "blocked"
        if signal.direction == "LONG":
            long_signals += 1
        else:
            short_signals += 1
        setup_mode_counts[signal.setup_mode] = setup_mode_counts.get(signal.setup_mode, 0) + 1
        band_touched_counts[signal.band_touched] = band_touched_counts.get(signal.band_touched, 0) + 1
        rows.append(
            _signal_to_row(
                scanner_run_id=scanner_run_id,
                generated_at=run_started_at,
                symbol=config.symbol,
                when=when,
                signal=signal,
                session=session,
                cooldown_minutes=config.cooldown_minutes,
                cooldown_status=cooldown_status,
                cooldown_accepted=cooldown_accept,
                cooldown_block_reason=reason,
                last_signal_timestamp=last_ts,
                latest_by_timeframe=latest_by_tf,
                data_rows_used={tf: int(len(frame)) for tf, frame in market_slice.items()},
            )
        )

    runtime_seconds = round(perf_counter() - started_perf, 4)
    run_finished_at = _utc_now_iso()
    existing_rows = _load_existing_signal_rows(config.output_dir / "paper_signals.csv") if config.incremental and config.append else []
    existing_keys = {_signal_key(row) for row in existing_rows}
    new_rows: list[dict[str, Any]] = []
    duplicates_skipped = 0
    for row in rows:
        key = _signal_key(row)
        if key in existing_keys:
            duplicates_skipped += 1
            continue
        existing_keys.add(key)
        new_rows.append(row)
    output_rows = existing_rows + new_rows if config.incremental and config.append else rows
    latest_processed = _parse_utc(driver_times[-1]).isoformat() if driver_times else previous_last_processed
    mode = "paper_shadow_incremental" if config.incremental else MODE
    summary = {
        "scanner_run_id": scanner_run_id,
        "mode": mode,
        "incremental": config.incremental,
        "state_file": str(state_path) if config.incremental else None,
        "previous_last_processed_timestamp": previous_last_processed,
        "new_last_processed_timestamp": latest_processed,
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "runtime_seconds": runtime_seconds,
        "symbol": config.symbol,
        "strategy": STRATEGY_NAME,
        "data_dir": config.data_dir,
        "output_dir": str(config.output_dir),
        "dry_run": config.dry_run,
        "cooldown_minutes": config.cooldown_minutes,
        "timeframes": list(config.timeframes),
        "latest_available_timestamp_by_timeframe": latest_by_tf,
        "earliest_available_timestamp_by_timeframe": earliest_by_tf,
        "latest_data_timestamp": latest_by_tf.get("M15"),
        "driver_timeframe": "M15",
        "driver_candles_seen": int(len(driver_times)),
        "driver_candles_processed": int(len(driver_times)),
        "signals_detected": len(rows),
        "signals_accepted": accepted,
        "signals_blocked_by_cooldown": blocked,
        "paper_signals_total_after_run": len(output_rows),
        "new_paper_signals_this_run": len(new_rows) if config.incremental else len(rows),
        "duplicates_skipped": duplicates_skipped,
        "long_signals": long_signals,
        "short_signals": short_signals,
        "setup_mode_counts": setup_mode_counts,
        "band_touched_counts": band_touched_counts,
        "no_signal_reason": None if rows else ("no_new_driver_candles_to_process" if config.incremental and not driver_times else "no_strategy_3_signal_on_latest_driver_candle"),
        "strategy_diagnostics": diagnostics.to_dict(),
        "verdict_flags": [],
        "htf_freshness": htf_diagnostic,
        "htf_freshness_status": htf_diagnostic.get("htf_freshness_status") if htf_diagnostic else None,
        "stale_timeframes": htf_diagnostic.get("stale_timeframes", []) if htf_diagnostic else [],
        "scanner_blocked_due_to_stale_htf": False,
        "paper_signals_clean_for_validation": not bool(htf_diagnostic) or bool(htf_diagnostic.get("paper_signals_clean_for_validation", True)),
        "safety": dict(SAFETY_FLAGS),
    }
    _write_outputs(output_dir=config.output_dir, rows=output_rows, summary=summary)
    if config.incremental:
        prior_runs = int(previous_state.get("total_incremental_runs", 0) or 0)
        state = {
            "symbol": config.symbol,
            "strategy": STRATEGY_NAME,
            "cooldown_minutes": config.cooldown_minutes,
            "last_processed_timestamp": latest_processed,
            "last_run_started_at": run_started_at,
            "last_run_finished_at": run_finished_at,
            "latest_available_timestamp": latest_by_tf.get("M15"),
            "total_incremental_runs": prior_runs + 1,
            "total_driver_candles_processed": int(previous_state.get("total_driver_candles_processed", 0) or 0) + len(driver_times),
            "total_signals_detected": int(previous_state.get("total_signals_detected", 0) or 0) + len(rows),
            "total_signals_accepted": int(previous_state.get("total_signals_accepted", 0) or 0) + accepted,
            "total_signals_blocked": int(previous_state.get("total_signals_blocked", 0) or 0) + blocked,
            "cooldown_state": {f"{symbol}|{direction}": ts.isoformat() for (symbol, direction), ts in last_accepted_by_key.items()},
            "safety": {
                "live_trading_enabled": False,
                "telegram_enabled": False,
                "order_execution_enabled": False,
            },
        }
        _write_state(state_path, state)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    timeframes = [item.strip() for item in str(args.timeframes).split(",") if item.strip()]
    config = ShadowScannerConfig(
        symbol=args.symbol,
        timeframes=timeframes,
        data_dir=args.data_dir,
        output_dir=Path(args.output_dir),
        cooldown_minutes=int(args.cooldown_minutes),
        dry_run=bool(args.dry_run),
        scan_driver_bars=int(args.scan_driver_bars),
        incremental=bool(args.incremental),
        state_file=Path(args.state_file) if args.state_file else None,
        from_timestamp=args.from_timestamp,
        reset_state=bool(args.reset_state),
        append=bool(args.append),
        max_candles_per_run=args.max_candles_per_run,
        enforce_htf_freshness=not bool(args.allow_stale_htf_context),
        htf_report_dir=Path(args.htf_report_dir) if args.htf_report_dir else None,
    )
    summary = run_scanner(config)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
