from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_xauusd_data import read_candle_csv

TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
TIMEFRAME_DURATIONS = {
    "M1": pd.Timedelta(minutes=1),
    "M5": pd.Timedelta(minutes=5),
    "M15": pd.Timedelta(minutes=15),
    "H1": pd.Timedelta(hours=1),
    "H4": pd.Timedelta(hours=4),
    "D1": pd.Timedelta(days=1),
}
SAFETY = {
    "live_trading_enabled": False,
    "order_execution_enabled": False,
    "telegram_enabled": False,
    "broker_order_functions_called": False,
    "order_send_called": False,
}


@dataclass(frozen=True)
class CollectorConfig:
    symbol: str
    symbol_broker: str
    timeframes: list[str]
    output_dir: Path
    data_dir: Path
    days_back: int
    date_from: datetime | None
    date_to: datetime
    dry_run: bool
    write: bool
    overwrite: bool
    allow_large_fetch: bool
    allow_timezone_warning: bool
    allow_overlap_mismatch: bool
    include_forming_candles: bool
    closed_candle_grace_seconds: int
    overlap_price_tolerance_usd: float
    report_dir: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch XAUUSD OHLC candles from local MT5 into incoming_data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--symbol-broker", default=None)
    parser.add_argument("--timeframes", default=",".join(TIMEFRAMES))
    parser.add_argument("--output-dir", default="incoming_data/XAUUSD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--days-back", type=int, default=7)
    parser.add_argument("--from", dest="date_from", default=None)
    parser.add_argument("--to", dest="date_to", default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--write", action="store_true", default=False)
    parser.add_argument("--overwrite", action="store_true", default=False)
    parser.add_argument("--allow-large-fetch", action="store_true", default=False)
    parser.add_argument("--allow-timezone-warning", action="store_true", default=False)
    parser.add_argument("--allow-overlap-mismatch", action="store_true", default=False)
    parser.add_argument("--include-forming-candles", action="store_true", default=False)
    parser.add_argument("--closed-candle-grace-seconds", type=int, default=5)
    parser.add_argument("--overlap-price-tolerance-usd", type=float, default=0.10)
    parser.add_argument("--report-dir", default="backtests/reports/strategy_3_mt5_data_collector")
    return parser.parse_args(argv)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def import_mt5() -> Any | None:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ModuleNotFoundError:
        return None
    return mt5


def days_back_safety(days_back: int, allow_large_fetch: bool) -> tuple[str, list[str], bool]:
    if days_back > 365:
        return "high", ["MT5_FETCH_RANGE_TOO_LARGE"], True
    if days_back > 90 and not allow_large_fetch:
        return "high", ["MT5_FETCH_RANGE_REQUIRES_CONFIRMATION"], True
    if days_back > 90:
        return "high", ["MT5_FETCH_RANGE_WARNING"], False
    if days_back > 30:
        return "medium", ["MT5_FETCH_RANGE_WARNING"], False
    return "low", [], False


def timeframe_mapping(mt5: Any) -> dict[str, Any]:
    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


def normalize_rates(rates: Any) -> pd.DataFrame:
    if rates is None or len(rates) == 0:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume", "spread"])
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    if "tick_volume" not in df.columns and "volume" in df.columns:
        df["tick_volume"] = df["volume"]
    if "spread" not in df.columns:
        df["spread"] = 0
    out = df[["time", "open", "high", "low", "close", "tick_volume", "spread"]].copy()
    out = out.drop_duplicates(subset=["time"], keep="last").sort_values("time").reset_index(drop=True)
    return out


def _format_for_incoming(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True).dt.strftime("%Y.%m.%d %H:%M")
    return out


def filter_closed_candles(
    frames: dict[str, pd.DataFrame],
    *,
    now_utc: datetime,
    include_forming_candles: bool,
    grace_seconds: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, int], dict[str, str | None]]:
    if include_forming_candles:
        latest = {
            tf: (pd.to_datetime(df["time"], utc=True).max().isoformat() if not df.empty else None)
            for tf, df in frames.items()
        }
        return {tf: df.copy() for tf, df in frames.items()}, {tf: 0 for tf in frames}, latest

    threshold = pd.Timestamp(now_utc) - pd.Timedelta(seconds=max(0, grace_seconds))
    filtered: dict[str, pd.DataFrame] = {}
    skipped: dict[str, int] = {}
    latest_closed: dict[str, str | None] = {}
    for tf, df in frames.items():
        if df.empty:
            filtered[tf] = df.copy()
            skipped[tf] = 0
            latest_closed[tf] = None
            continue
        duration = TIMEFRAME_DURATIONS[tf]
        out = df.copy()
        times = pd.to_datetime(out["time"], utc=True)
        closed_mask = times + duration <= threshold
        filtered_df = out.loc[closed_mask].reset_index(drop=True)
        filtered[tf] = filtered_df
        skipped[tf] = int((~closed_mask).sum())
        latest_closed[tf] = pd.to_datetime(filtered_df["time"], utc=True).max().isoformat() if not filtered_df.empty else None
    return filtered, skipped, latest_closed


def validate_timezone(frames: dict[str, pd.DataFrame], now_utc: datetime, tolerance_minutes: int = 5) -> tuple[list[str], dict[str, str | None]]:
    warnings: list[str] = []
    latest: dict[str, str | None] = {}
    limit = pd.Timestamp(now_utc) + pd.Timedelta(minutes=tolerance_minutes)
    for tf, df in frames.items():
        if df.empty:
            latest[tf] = None
            continue
        last = pd.to_datetime(df["time"], utc=True).max()
        latest[tf] = last.isoformat()
        if last > limit:
            warnings.append(f"{tf}:last_timestamp_in_future:{last.isoformat()}")
        if not pd.to_datetime(df["time"], utc=True).is_monotonic_increasing:
            warnings.append(f"{tf}:non_monotonic_after_conversion")
    return warnings, latest


def _ohlcv_payload(row: pd.Series, suffix: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for col in ("open", "high", "low", "close", "tick_volume", "spread"):
        name = f"{col}{suffix}"
        if name in row:
            value = row[name]
            payload[col] = None if pd.isna(value) else float(value)
    return payload


def _existing_overlap(existing: pd.DataFrame, fetched: pd.DataFrame, tf: str, tolerance: float, *, closed_only: bool = False) -> dict[str, Any]:
    if existing.empty or fetched.empty:
        return {"verdict": "OVERLAP_NO_DATA", "overlap_rows_existing": 0, "overlap_rows_fetched": 0, "overlap_matched_rows": 0, "overlap_mismatched_rows": 0, "overlap_match_rate": None, "worst_ohlc_diff": None, "first_mismatch_timestamp": None, "last_mismatch_timestamp": None, "mismatch_example_existing_ohlcv": None, "mismatch_example_incoming_ohlcv": None, "overlap_window_start": None, "overlap_window_end": None, "overlap_validation_basis": "closed_candles_only" if closed_only else "all_fetched_candles"}
    existing = existing.copy()
    fetched = fetched.copy()
    existing["time"] = pd.to_datetime(existing["time"], utc=True)
    fetched["time"] = pd.to_datetime(fetched["time"], utc=True)
    last = existing["time"].max()
    start = last - pd.Timedelta(hours=24)
    e = existing[(existing["time"] >= start) & (existing["time"] <= last)]
    f = fetched[(fetched["time"] >= start) & (fetched["time"] <= last)]
    merged = e.merge(f, on="time", suffixes=("_existing", "_fetched"))
    if merged.empty:
        return {"verdict": "OVERLAP_NO_DATA", "overlap_rows_existing": int(len(e)), "overlap_rows_fetched": int(len(f)), "overlap_matched_rows": 0, "overlap_mismatched_rows": 0, "overlap_match_rate": None, "worst_ohlc_diff": None, "first_mismatch_timestamp": None, "last_mismatch_timestamp": None, "mismatch_example_existing_ohlcv": None, "mismatch_example_incoming_ohlcv": None, "overlap_window_start": start.isoformat(), "overlap_window_end": last.isoformat(), "overlap_validation_basis": "closed_candles_only" if closed_only else "all_fetched_candles"}
    diffs = []
    for col in ("open", "high", "low", "close"):
        diffs.append((merged[f"{col}_existing"].astype(float) - merged[f"{col}_fetched"].astype(float)).abs())
    max_diff = pd.concat(diffs, axis=1).max(axis=1)
    matched = max_diff <= tolerance
    match_rate = float(matched.mean())
    if match_rate == 1.0:
        verdict = "OVERLAP_MATCH_100_CLOSED_CANDLES" if closed_only else "OVERLAP_MATCH_100"
    elif match_rate >= 0.95:
        verdict = "OVERLAP_MATCH_GT_95"
    else:
        verdict = "OVERLAP_MATCH_LT_95"
    mismatch_rows = merged.loc[~matched]
    first_mismatch = mismatch_rows["time"].iloc[0].isoformat() if not mismatch_rows.empty else None
    last_mismatch = mismatch_rows["time"].iloc[-1].isoformat() if not mismatch_rows.empty else None
    mismatch_example_existing = _ohlcv_payload(mismatch_rows.iloc[0], "_existing") if not mismatch_rows.empty else None
    mismatch_example_incoming = _ohlcv_payload(mismatch_rows.iloc[0], "_fetched") if not mismatch_rows.empty else None
    return {
        "verdict": verdict,
        "overlap_rows_existing": int(len(e)),
        "overlap_rows_fetched": int(len(f)),
        "overlap_matched_rows": int(matched.sum()),
        "overlap_mismatched_rows": int((~matched).sum()),
        "overlap_match_rate": round(match_rate, 4),
        "worst_ohlc_diff": round(float(max_diff.max()), 5),
        "first_mismatch_timestamp": first_mismatch,
        "last_mismatch_timestamp": last_mismatch,
        "mismatch_example_existing_ohlcv": mismatch_example_existing,
        "mismatch_example_incoming_ohlcv": mismatch_example_incoming,
        "overlap_window_start": start.isoformat(),
        "overlap_window_end": last.isoformat(),
        "overlap_validation_basis": "closed_candles_only" if closed_only else "all_fetched_candles",
    }


def validate_overlap(frames: dict[str, pd.DataFrame], data_dir: Path, symbol: str, tolerance: float, *, closed_only: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tf, fetched in frames.items():
        path = data_dir / symbol / f"{tf}.csv"
        if not path.exists():
            out[tf] = {"verdict": "OVERLAP_NO_DATA", "overlap_validation_basis": "closed_candles_only" if closed_only else "all_fetched_candles"}
            continue
        existing = read_candle_csv(path).frame
        out[tf] = _existing_overlap(existing, fetched, tf, tolerance, closed_only=closed_only)
    return out


def _symbol_suggestions(mt5: Any) -> list[str]:
    try:
        symbols = mt5.symbols_get()
    except Exception:
        return []
    names = [getattr(sym, "name", "") for sym in symbols or []]
    return sorted({name for name in names if "XAU" in name.upper() or "GOLD" in name.upper()})[:25]


def _write_reports(summary: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "mt5_fetch_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    lines = [
        "# Strategy 3 MT5 Data Collector",
        "",
        f"- project_symbol: `{summary['project_symbol']}`",
        f"- broker_symbol: `{summary['broker_symbol']}`",
        f"- dry_run: `{summary['dry_run']}`",
        f"- write_enabled: `{summary['write_enabled']}`",
        f"- verdict_flags: `{', '.join(summary['verdict_flags'])}`",
        "",
        "| TF | rows | first | last | overlap verdict |",
        "|---|---:|---|---|---|",
    ]
    for tf in summary["timeframes"]:
        lines.append(
            f"| {tf} | {summary['rows_fetched_by_timeframe'].get(tf, 0)} | "
            f"{summary['first_timestamp_by_timeframe'].get(tf)} | {summary['last_timestamp_by_timeframe'].get(tf)} | "
            f"{summary['overlap_validation']['verdict_by_timeframe'].get(tf)} |"
        )
    (report_dir / "mt5_fetch_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_collector(cfg: CollectorConfig, mt5_module: Any | None = None) -> dict[str, Any]:
    started = perf_counter()
    run_started_at = datetime.now(timezone.utc).isoformat()
    risk, range_flags, range_block = days_back_safety(cfg.days_back, cfg.allow_large_fetch)
    summary: dict[str, Any] = {
        "run_started_at": run_started_at,
        "project_symbol": cfg.symbol,
        "broker_symbol": cfg.symbol_broker,
        "timeframes": cfg.timeframes,
        "date_from": (cfg.date_from or (cfg.date_to - timedelta(days=cfg.days_back))).isoformat(),
        "date_to": cfg.date_to.isoformat(),
        "output_dir": str(cfg.output_dir),
        "dry_run": cfg.dry_run or not cfg.write,
        "write_enabled": cfg.write,
        "overwrite_enabled": cfg.overwrite,
        "closed_candle_only": not cfg.include_forming_candles,
        "include_forming_candles": cfg.include_forming_candles,
        "closed_candle_grace_seconds": cfg.closed_candle_grace_seconds,
        "mt5_initialize_ok": False,
        "symbol_select_ok": False,
        "suggested_symbols": [],
        "rows_fetched_by_timeframe": {},
        "rows_after_closed_filter_by_timeframe": {},
        "rows_written_by_timeframe": {},
        "first_timestamp_by_timeframe": {},
        "last_timestamp_by_timeframe": {},
        "latest_fetched_timestamp_by_timeframe": {},
        "latest_closed_timestamp_by_timeframe": {},
        "forming_candles_skipped_by_timeframe": {},
        "files_written": [],
        "timezone": {
            "now_utc": datetime.now(timezone.utc).isoformat(),
            "terminal_info_available": False,
            "terminal_timezone_info": {},
            "conversion_mode_used": "mt5_epoch_seconds_to_utc",
            "timezone_warnings": [],
        },
        "overlap_validation": {
            "overlap_match_rate_by_timeframe": {},
            "worst_ohlc_diff_by_timeframe": {},
            "verdict_by_timeframe": {},
            "details_by_timeframe": {},
            "overlap_validation_basis": "closed_candles_only",
        },
        "raw_overlap_validation": {
            "verdict_by_timeframe": {},
            "details_by_timeframe": {},
        },
        "timeframes_quarantined_by_overlap": [],
        "blocking_fetch_error": False,
        "non_blocking_warnings": [],
        "days_back_safety": {
            "requested_days_back": cfg.days_back,
            "allow_large_fetch": cfg.allow_large_fetch,
            "estimated_risk_level": risk,
            "verdict": range_flags[0] if range_flags else "MT5_FETCH_RANGE_OK",
        },
        "verdict_flags": list(range_flags),
        "safety": dict(SAFETY),
    }
    if range_block:
        summary["run_finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["runtime_seconds"] = round(perf_counter() - started, 4)
        _write_reports(summary, cfg.report_dir)
        return summary
    mt5 = mt5_module or import_mt5()
    if mt5 is None:
        summary["verdict_flags"].append("MT5_PACKAGE_MISSING")
        summary["message"] = "MetaTrader5 Python package missing. Install with: pip install MetaTrader5"
        summary["run_finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["runtime_seconds"] = round(perf_counter() - started, 4)
        _write_reports(summary, cfg.report_dir)
        return summary
    initialized = False
    try:
        initialized = bool(mt5.initialize())
        summary["mt5_initialize_ok"] = initialized
        if not initialized:
            summary["mt5_last_error"] = str(mt5.last_error())
            summary["verdict_flags"].append("MT5_INITIALIZE_FAILED")
            summary["message"] = "MT5 initialize failed. Keep the MT5 terminal open and logged in, then retry."
            return summary
        try:
            terminal_info = mt5.terminal_info()
            summary["timezone"]["terminal_info_available"] = terminal_info is not None
            summary["timezone"]["terminal_timezone_info"] = dict(getattr(terminal_info, "_asdict", lambda: {})()) if terminal_info is not None else {}
        except Exception:
            pass
        selected = bool(mt5.symbol_select(cfg.symbol_broker, True))
        summary["symbol_select_ok"] = selected
        if not selected:
            summary["suggested_symbols"] = _symbol_suggestions(mt5)
            summary["verdict_flags"].append("MT5_SYMBOL_SELECT_FAILED")
            return summary
        mapping = timeframe_mapping(mt5)
        date_from = cfg.date_from or (cfg.date_to - timedelta(days=cfg.days_back))
        frames: dict[str, pd.DataFrame] = {}
        for tf in cfg.timeframes:
            rates = mt5.copy_rates_range(cfg.symbol_broker, mapping[tf], date_from, cfg.date_to)
            frame = normalize_rates(rates)
            frames[tf] = frame
            summary["rows_fetched_by_timeframe"][tf] = int(len(frame))
            summary["latest_fetched_timestamp_by_timeframe"][tf] = frame["time"].max().isoformat() if not frame.empty else None
        if not any(summary["rows_fetched_by_timeframe"].values()):
            summary["verdict_flags"].append("MT5_NO_RATES_RETURNED")
        if any(v == 0 for v in summary["rows_fetched_by_timeframe"].values()):
            summary["verdict_flags"].append("MT5_PARTIAL_TIMEFRAME_FAILURE")
        tz_warnings, _ = validate_timezone(frames, datetime.now(timezone.utc))
        summary["timezone"]["timezone_warnings"] = tz_warnings
        if tz_warnings:
            summary["verdict_flags"].append("MT5_TIMEZONE_MISMATCH_DETECTED")
        raw_overlap = validate_overlap(frames, cfg.data_dir, cfg.symbol, cfg.overlap_price_tolerance_usd, closed_only=False)
        closed_frames, skipped_forming, latest_closed = filter_closed_candles(
            frames,
            now_utc=cfg.date_to,
            include_forming_candles=cfg.include_forming_candles,
            grace_seconds=cfg.closed_candle_grace_seconds,
        )
        summary["forming_candles_skipped_by_timeframe"] = skipped_forming
        summary["latest_closed_timestamp_by_timeframe"] = latest_closed
        for tf, frame in closed_frames.items():
            summary["rows_after_closed_filter_by_timeframe"][tf] = int(len(frame))
            summary["first_timestamp_by_timeframe"][tf] = frame["time"].min().isoformat() if not frame.empty else None
            summary["last_timestamp_by_timeframe"][tf] = frame["time"].max().isoformat() if not frame.empty else None
        if any(skipped_forming.values()):
            summary["verdict_flags"].append("FORMING_CANDLES_SKIPPED")
        overlap = validate_overlap(closed_frames, cfg.data_dir, cfg.symbol, cfg.overlap_price_tolerance_usd, closed_only=not cfg.include_forming_candles)
        for tf, item in raw_overlap.items():
            summary["raw_overlap_validation"]["verdict_by_timeframe"][tf] = item.get("verdict")
            summary["raw_overlap_validation"]["details_by_timeframe"][tf] = item
        for tf, item in overlap.items():
            summary["overlap_validation"]["overlap_match_rate_by_timeframe"][tf] = item.get("overlap_match_rate")
            summary["overlap_validation"]["worst_ohlc_diff_by_timeframe"][tf] = item.get("worst_ohlc_diff")
            summary["overlap_validation"]["verdict_by_timeframe"][tf] = item.get("verdict")
            summary["overlap_validation"]["details_by_timeframe"][tf] = item
            if item.get("verdict"):
                summary["verdict_flags"].append(str(item["verdict"]))
            raw_verdict = raw_overlap.get(tf, {}).get("verdict")
            if raw_verdict == "OVERLAP_MATCH_LT_95" and item.get("verdict") != "OVERLAP_MATCH_LT_95" and skipped_forming.get(tf, 0) > 0:
                warning = f"{tf}:forming_candle_overlap_mismatch_ignored"
                summary["non_blocking_warnings"].append(warning)
                summary["verdict_flags"].append("HTF_FORMING_CANDLE_MISMATCH_IGNORED")
        overlap_blocked_timeframes = [
            tf for tf, item in overlap.items() if item.get("verdict") == "OVERLAP_MATCH_LT_95"
        ]
        htf_quarantine_timeframes: list[str] = []
        lower_timeframe_block = False
        if overlap_blocked_timeframes and not cfg.allow_overlap_mismatch:
            lower_timeframe_block = any(tf not in {"H4", "D1"} for tf in overlap_blocked_timeframes)
            if not lower_timeframe_block:
                htf_quarantine_timeframes = overlap_blocked_timeframes
                summary["timeframes_quarantined_by_overlap"] = list(htf_quarantine_timeframes)
                summary["non_blocking_warnings"].extend(
                    f"{tf}:htf_overlap_mismatch_quarantined" for tf in htf_quarantine_timeframes
                )
                summary["verdict_flags"].append("HTF_OVERLAP_MISMATCH_QUARANTINED")
        overlap_block = bool(overlap_blocked_timeframes) and lower_timeframe_block and not cfg.allow_overlap_mismatch
        timezone_block = bool(tz_warnings) and not cfg.allow_timezone_warning
        summary["blocking_fetch_error"] = bool(overlap_block or timezone_block)
        if cfg.write and not cfg.dry_run and not overlap_block and not timezone_block:
            cfg.output_dir.mkdir(parents=True, exist_ok=True)
            for tf, frame in closed_frames.items():
                if tf in htf_quarantine_timeframes:
                    summary["rows_written_by_timeframe"][tf] = 0
                    continue
                out_path = cfg.output_dir / f"{tf}.csv"
                if out_path.exists() and not cfg.overwrite:
                    summary["verdict_flags"].append("MT5_OUTPUT_EXISTS_OVERWRITE_REQUIRED")
                    summary["rows_written_by_timeframe"][tf] = 0
                    continue
                _format_for_incoming(frame).to_csv(out_path, index=False, encoding="utf-8")
                summary["files_written"].append(str(out_path))
                summary["rows_written_by_timeframe"][tf] = int(len(frame))
            summary["verdict_flags"].append("MT5_INCOMING_CSVS_WRITTEN")
        elif cfg.dry_run or not cfg.write:
            summary["verdict_flags"].append("MT5_WRITE_DISABLED_DRY_RUN")
        else:
            summary["verdict_flags"].append("MT5_FETCH_WARNINGS")
        if (
            not overlap_block
            and not timezone_block
            and not any(
                flag.startswith("MT5_")
                and flag
                not in {"MT5_WRITE_DISABLED_DRY_RUN", "MT5_INCOMING_CSVS_WRITTEN", "MT5_FETCH_RANGE_WARNING"}
                for flag in summary["verdict_flags"]
            )
        ):
            summary["verdict_flags"].append("MT5_FETCH_OK")
        return summary
    finally:
        if mt5 is not None and initialized:
            try:
                mt5.shutdown()
            except Exception:
                pass
        summary["run_finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["runtime_seconds"] = round(perf_counter() - started, 4)
        summary["verdict_flags"] = list(dict.fromkeys(summary["verdict_flags"]))
        _write_reports(summary, cfg.report_dir)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    date_to = _parse_dt(args.date_to) or datetime.now(timezone.utc)
    cfg = CollectorConfig(
        symbol=args.symbol,
        symbol_broker=args.symbol_broker or args.symbol,
        timeframes=_split(args.timeframes),
        output_dir=Path(args.output_dir),
        data_dir=Path(args.data_dir),
        days_back=int(args.days_back),
        date_from=_parse_dt(args.date_from),
        date_to=date_to,
        dry_run=bool(args.dry_run or not args.write),
        write=bool(args.write),
        overwrite=bool(args.overwrite),
        allow_large_fetch=bool(args.allow_large_fetch),
        allow_timezone_warning=bool(args.allow_timezone_warning),
        allow_overlap_mismatch=bool(args.allow_overlap_mismatch),
        overlap_price_tolerance_usd=float(args.overlap_price_tolerance_usd),
        include_forming_candles=bool(args.include_forming_candles),
        closed_candle_grace_seconds=int(args.closed_candle_grace_seconds),
        report_dir=Path(args.report_dir),
    )
    summary = run_collector(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
