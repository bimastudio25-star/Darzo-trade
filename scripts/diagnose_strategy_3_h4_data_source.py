from __future__ import annotations

import argparse
import json
import shutil
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

from scripts.audit_xauusd_data import read_candle_csv, validate_frame
from scripts.fetch_xauusd_mt5_candles import (
    filter_closed_candles,
    import_mt5,
    normalize_rates,
    timeframe_mapping,
)
from scripts.import_xauusd_candles import write_project_csv
from scripts.strategy_3_htf_freshness import expected_latest_closed_timestamp

SAFETY = {
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "order_execution_enabled": False,
    "broker_execution_enabled": False,
    "broker_order_functions_called": False,
    "order_send_called": False,
}


@dataclass(frozen=True)
class H4DiagnosticConfig:
    symbol: str
    symbol_broker: str
    data_dir: Path
    output_dir: Path
    lookback_bars: int
    dry_run: bool
    include_forming_candles: bool
    closed_candle_grace_seconds: int
    candidate_rebuild_output: bool
    apply_rebuild: bool
    price_tolerance_usd: float = 0.10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Strategy 3 XAUUSD H4 data source mismatch")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--symbol-broker", default=None)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_h4_data_source_diagnostic")
    parser.add_argument("--lookback-bars", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--include-forming-candles", action="store_true", default=False)
    parser.add_argument("--closed-candle-grace-seconds", type=int, default=5)
    parser.add_argument("--candidate-rebuild-output", action="store_true", default=True)
    parser.add_argument("--no-candidate-rebuild-output", dest="candidate_rebuild_output", action="store_false")
    parser.add_argument("--apply-rebuild", action="store_true", default=False)
    return parser.parse_args(argv)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _latest_timestamp(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty or "time" not in df.columns:
        return None
    times = pd.to_datetime(df["time"], utc=True, errors="coerce").dropna()
    return times.max() if not times.empty else None


def _first_timestamp(df: pd.DataFrame) -> pd.Timestamp | None:
    if df.empty or "time" not in df.columns:
        return None
    times = pd.to_datetime(df["time"], utc=True, errors="coerce").dropna()
    return times.min() if not times.empty else None


def _inferred_interval_seconds(df: pd.DataFrame) -> float | None:
    if df.empty or "time" not in df.columns:
        return None
    times = pd.to_datetime(df["time"], utc=True, errors="coerce").dropna().sort_values()
    diffs = times.diff().dropna()
    if diffs.empty:
        return None
    return float(diffs.mode().iloc[0].total_seconds()) if not diffs.mode().empty else float(diffs.median().total_seconds())


def _mod_4h_distribution(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "time" not in df.columns:
        return {}
    times = pd.to_datetime(df["time"], utc=True, errors="coerce").dropna()
    out: dict[str, int] = {}
    for ts in times:
        key = str(int(ts.hour % 4))
        out[key] = out.get(key, 0) + 1
    return out


def _ohlcv(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in ("open", "high", "low", "close", "tick_volume", "spread"):
        if col in row:
            value = row[col]
            out[col] = None if pd.isna(value) else float(value)
    return out


def _ohlcv_with_suffix(row: pd.Series, suffix: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in ("open", "high", "low", "close", "tick_volume", "spread"):
        name = f"{col}_{suffix}"
        if name in row:
            value = row[name]
            out[col] = None if pd.isna(value) else float(value)
    return out


def load_local_h4(data_dir: Path, symbol: str) -> tuple[pd.DataFrame, dict[str, Any], list[str], bool]:
    path = data_dir / symbol / "H4.csv"
    if not path.exists():
        return pd.DataFrame(), {"path": str(path), "exists": False}, [], True
    read = read_candle_csv(path)
    frame = read.frame.copy()
    meta = validate_frame(frame, "H4")
    meta.update(
        {
            "path": str(path),
            "exists": True,
            "schema": read.schema,
            "timestamp_has_time": read.timestamp_has_time,
            "row_count": int(len(frame)),
            "first_timestamp": _iso(_first_timestamp(frame)),
            "latest_timestamp": _iso(_latest_timestamp(frame)),
            "duplicate_count": int(meta.get("duplicate_timestamps", 0)),
            "gap_count": int(meta.get("gaps", 0)),
            "inferred_bar_interval_seconds": _inferred_interval_seconds(frame),
        }
    )
    return frame, meta, read.schema, read.timestamp_has_time


def fetch_mt5_h4(
    *,
    symbol_broker: str,
    lookback_bars: int,
    include_forming_candles: bool,
    closed_candle_grace_seconds: int,
    mt5_module: Any | None = None,
    now_utc: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    mt5 = mt5_module or import_mt5()
    now = now_utc or datetime.now(timezone.utc)
    meta: dict[str, Any] = {
        "symbol_broker": symbol_broker,
        "row_count": 0,
        "mt5_initialize_ok": False,
        "symbol_select_ok": False,
        "forming_candles_removed": 0,
        "safety": dict(SAFETY),
    }
    if mt5 is None:
        meta["verdict_flags"] = ["MT5_PACKAGE_MISSING"]
        meta["message"] = "MetaTrader5 Python package missing. Install with: pip install MetaTrader5"
        return pd.DataFrame(), meta
    initialized = False
    try:
        initialized = bool(mt5.initialize())
        meta["mt5_initialize_ok"] = initialized
        if not initialized:
            meta["verdict_flags"] = ["MT5_INITIALIZE_FAILED"]
            try:
                meta["mt5_last_error"] = str(mt5.last_error())
            except Exception:
                pass
            return pd.DataFrame(), meta
        selected = bool(mt5.symbol_select(symbol_broker, True))
        meta["symbol_select_ok"] = selected
        if not selected:
            meta["verdict_flags"] = ["MT5_SYMBOL_SELECT_FAILED"]
            return pd.DataFrame(), meta
        mapping = timeframe_mapping(mt5)
        rates = None
        if hasattr(mt5, "copy_rates_from_pos"):
            rates = mt5.copy_rates_from_pos(symbol_broker, mapping["H4"], 0, int(lookback_bars))
        else:
            date_from = now - timedelta(hours=max(4, int(lookback_bars)) * 4 + 24)
            rates = mt5.copy_rates_range(symbol_broker, mapping["H4"], date_from, now)
        raw = normalize_rates(rates)
        closed_frames, skipped, latest_closed = filter_closed_candles(
            {"H4": raw},
            now_utc=now,
            include_forming_candles=include_forming_candles,
            grace_seconds=closed_candle_grace_seconds,
        )
        frame = closed_frames["H4"]
        validation = validate_frame(frame, "H4")
        meta.update(
            {
                "row_count": int(len(frame)),
                "raw_row_count": int(len(raw)),
                "first_timestamp": _iso(_first_timestamp(frame)),
                "latest_raw_timestamp": _iso(_latest_timestamp(raw)),
                "latest_closed_timestamp": latest_closed.get("H4"),
                "forming_candles_removed": int(skipped.get("H4", 0)),
                "duplicate_count": int(validation.get("duplicate_timestamps", 0)),
                "gap_count": int(validation.get("gaps", 0)),
                "inferred_bar_interval_seconds": _inferred_interval_seconds(frame),
                "verdict_flags": [] if not frame.empty else ["MT5_NO_H4_RATES_RETURNED"],
            }
        )
        return frame, meta
    finally:
        if mt5 is not None and initialized:
            try:
                mt5.shutdown()
            except Exception:
                pass


def compare_h4_frames(local: pd.DataFrame, mt5: pd.DataFrame, price_tolerance_usd: float) -> dict[str, Any]:
    if local.empty or mt5.empty:
        return {
            "overlap_count": 0,
            "match_count_ohlc": 0,
            "match_rate_ohlc": None,
            "match_count_ohlcv": 0,
            "match_rate_ohlcv": None,
            "first_mismatch_timestamp": None,
            "last_mismatch_timestamp": None,
            "worst_ohlc_diff": None,
            "worst_ohlc_diff_timestamp": None,
            "mismatch_examples": [],
            "mismatch_type": "no_overlap",
        }
    left = local.copy()
    right = mt5.copy()
    left["time"] = pd.to_datetime(left["time"], utc=True)
    right["time"] = pd.to_datetime(right["time"], utc=True)
    merged = left.merge(right, on="time", suffixes=("_local", "_mt5"))
    if merged.empty:
        return {
            "overlap_count": 0,
            "match_count_ohlc": 0,
            "match_rate_ohlc": None,
            "match_count_ohlcv": 0,
            "match_rate_ohlcv": None,
            "first_mismatch_timestamp": None,
            "last_mismatch_timestamp": None,
            "worst_ohlc_diff": None,
            "worst_ohlc_diff_timestamp": None,
            "mismatch_examples": [],
            "mismatch_type": "no_overlap",
        }
    diffs: dict[str, pd.Series] = {}
    for col in ("open", "high", "low", "close"):
        diffs[col] = (merged[f"{col}_local"].astype(float) - merged[f"{col}_mt5"].astype(float)).abs()
    ohlc_max = pd.concat(diffs.values(), axis=1).max(axis=1)
    ohlc_match = ohlc_max <= price_tolerance_usd
    volume_cols_present = "tick_volume_local" in merged.columns and "tick_volume_mt5" in merged.columns
    spread_cols_present = "spread_local" in merged.columns and "spread_mt5" in merged.columns
    volume_match = (
        merged["tick_volume_local"].fillna(0).astype(float).eq(merged["tick_volume_mt5"].fillna(0).astype(float))
        if volume_cols_present
        else pd.Series([True] * len(merged), index=merged.index)
    )
    spread_match = (
        merged["spread_local"].fillna(0).astype(float).eq(merged["spread_mt5"].fillna(0).astype(float))
        if spread_cols_present
        else pd.Series([True] * len(merged), index=merged.index)
    )
    ohlcv_match = ohlc_match & volume_match & spread_match
    ohlc_mismatch_rows = merged.loc[~ohlc_match].copy()
    ohlcv_mismatch_rows = merged.loc[~ohlcv_match].copy()
    material_first = pd.concat([ohlc_mismatch_rows, ohlcv_mismatch_rows.drop(index=ohlc_mismatch_rows.index, errors="ignore")])
    examples: list[dict[str, Any]] = []
    for idx, row in material_first.head(10).iterrows():
        examples.append(
            {
                "timestamp": row["time"].isoformat(),
                "local_ohlcv": _ohlcv_with_suffix(row, "local"),
                "mt5_ohlcv": _ohlcv_with_suffix(row, "mt5"),
                "diff_open": float(diffs["open"].loc[idx]),
                "diff_high": float(diffs["high"].loc[idx]),
                "diff_low": float(diffs["low"].loc[idx]),
                "diff_close": float(diffs["close"].loc[idx]),
                "diff_volume": (
                    float(abs(row.get("tick_volume_local", 0) - row.get("tick_volume_mt5", 0)))
                    if volume_cols_present
                    else None
                ),
                "materiality": "OHLC_MATERIAL" if float(ohlc_max.loc[idx]) > price_tolerance_usd else "VOLUME_OR_SPREAD_ONLY",
            }
        )
    worst_idx = ohlc_max.idxmax()
    match_rate_ohlc = float(ohlc_match.mean())
    match_rate_ohlcv = float(ohlcv_match.mean())
    if match_rate_ohlc == 1.0 and match_rate_ohlcv < 1.0:
        mismatch_type = "volume_only"
    elif match_rate_ohlc < 1.0:
        mismatch_type = "ohlc_material"
    elif match_rate_ohlcv == 1.0:
        mismatch_type = "none"
    else:
        mismatch_type = "spread_only"
    return {
        "overlap_count": int(len(merged)),
        "match_count_ohlc": int(ohlc_match.sum()),
        "match_rate_ohlc": round(match_rate_ohlc, 4),
        "match_count_ohlcv": int(ohlcv_match.sum()),
        "match_rate_ohlcv": round(match_rate_ohlcv, 4),
        "first_mismatch_timestamp": (
            ohlc_mismatch_rows["time"].iloc[0].isoformat()
            if not ohlc_mismatch_rows.empty
            else (ohlcv_mismatch_rows["time"].iloc[0].isoformat() if not ohlcv_mismatch_rows.empty else None)
        ),
        "last_mismatch_timestamp": (
            ohlc_mismatch_rows["time"].iloc[-1].isoformat()
            if not ohlc_mismatch_rows.empty
            else (ohlcv_mismatch_rows["time"].iloc[-1].isoformat() if not ohlcv_mismatch_rows.empty else None)
        ),
        "first_ohlc_mismatch_timestamp": ohlc_mismatch_rows["time"].iloc[0].isoformat() if not ohlc_mismatch_rows.empty else None,
        "last_ohlc_mismatch_timestamp": ohlc_mismatch_rows["time"].iloc[-1].isoformat() if not ohlc_mismatch_rows.empty else None,
        "first_ohlcv_mismatch_timestamp": ohlcv_mismatch_rows["time"].iloc[0].isoformat() if not ohlcv_mismatch_rows.empty else None,
        "last_ohlcv_mismatch_timestamp": ohlcv_mismatch_rows["time"].iloc[-1].isoformat() if not ohlcv_mismatch_rows.empty else None,
        "worst_ohlc_diff": round(float(ohlc_max.max()), 5),
        "worst_ohlc_diff_timestamp": merged.loc[worst_idx, "time"].isoformat(),
        "mismatch_examples": examples,
        "mismatch_type": mismatch_type,
    }


def timezone_shift_diagnostic(local: pd.DataFrame, mt5: pd.DataFrame, price_tolerance_usd: float) -> dict[str, Any]:
    shifts: dict[str, dict[str, Any]] = {}
    best_shift = 0
    best_rate = -1.0
    for shift in range(-3, 4):
        shifted = mt5.copy()
        if not shifted.empty and "time" in shifted.columns:
            shifted["time"] = pd.to_datetime(shifted["time"], utc=True) + pd.Timedelta(hours=shift)
        comparison = compare_h4_frames(local, shifted, price_tolerance_usd)
        rate = comparison.get("match_rate_ohlc")
        numeric_rate = -1.0 if rate is None else float(rate)
        shifts[str(shift)] = {
            "overlap_count": comparison.get("overlap_count"),
            "match_rate_ohlc": rate,
        }
        if numeric_rate > best_rate:
            best_rate = numeric_rate
            best_shift = shift
    baseline = shifts.get("0", {}).get("match_rate_ohlc")
    baseline_rate = -1.0 if baseline is None else float(baseline)
    return {
        "timestamp_mod_4h_local_distribution": _mod_4h_distribution(local),
        "timestamp_mod_4h_mt5_distribution": _mod_4h_distribution(mt5),
        "possible_shift_hours_tested": [-3, -2, -1, 0, 1, 2, 3],
        "shift_results": shifts,
        "best_shift_by_match_rate": best_shift,
        "best_shift_match_rate": None if best_rate < 0 else round(best_rate, 4),
        "timezone_shift_suspected": best_shift != 0 and best_rate >= 0.95 and best_rate > baseline_rate + 0.05,
    }


def append_rebuild_diagnostic(local: pd.DataFrame, mt5: pd.DataFrame, comparison: dict[str, Any]) -> dict[str, Any]:
    local_latest = _latest_timestamp(local)
    mt5_latest = _latest_timestamp(mt5)
    missing = mt5[pd.to_datetime(mt5["time"], utc=True) > local_latest].copy() if local_latest is not None and not mt5.empty else mt5.iloc[0:0].copy()
    match_rate = comparison.get("match_rate_ohlc")
    overlap_count = int(comparison.get("overlap_count", 0) or 0)
    ohlc_clean = match_rate is not None and float(match_rate) == 1.0
    can_append = bool(overlap_count > 0 and ohlc_clean and not missing.empty)
    block_reason = None
    if overlap_count == 0:
        block_reason = "no_timestamp_overlap"
    elif not ohlc_clean:
        block_reason = "overlap_ohlc_not_perfect"
    elif missing.empty:
        block_reason = "no_missing_closed_bars_after_local_latest"
    return {
        "local_latest_timestamp": _iso(local_latest),
        "mt5_latest_closed_timestamp": _iso(mt5_latest),
        "missing_closed_bars_after_local_latest": int(len(missing)),
        "can_append_safely": can_append,
        "append_block_reason": block_reason,
        "backup_required_before_apply": True,
    }


def classify_recommendation(
    *,
    local_meta: dict[str, Any],
    mt5_meta: dict[str, Any],
    comparison: dict[str, Any],
    timezone_diag: dict[str, Any],
    append_diag: dict[str, Any],
) -> str:
    if mt5_meta.get("verdict_flags"):
        return "INSUFFICIENT_MT5_HISTORY" if "MT5_NO_H4_RATES_RETURNED" in mt5_meta.get("verdict_flags", []) else "DO_NOT_RECOVER_UNSAFE"
    if int(mt5_meta.get("row_count", 0) or 0) < 20 or int(comparison.get("overlap_count", 0) or 0) < 5:
        return "INSUFFICIENT_MT5_HISTORY"
    if timezone_diag.get("timezone_shift_suspected"):
        return "TIMEZONE_BOUNDARY_MISMATCH"
    mismatch_type = comparison.get("mismatch_type")
    if mismatch_type == "ohlc_material":
        if (
            int(local_meta.get("duplicate_count", 0) or 0)
            or int(local_meta.get("invalid_ohlc_rows", 0) or 0)
            or int(local_meta.get("non_monotonic_timestamps", 0) or 0)
        ):
            return "LOCAL_H4_CORRUPT_REBUILD_CANDIDATE"
        return "MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW"
    if mismatch_type in {"volume_only", "spread_only"}:
        return "VOLUME_ONLY_MISMATCH_RELAX_VOLUME_OVERLAP"
    if append_diag.get("can_append_safely"):
        return "LOCAL_H4_STALE_APPEND_SAFE"
    match_rate = comparison.get("match_rate_ohlc")
    if match_rate is not None and float(match_rate) < 0.95:
        if (
            int(local_meta.get("duplicate_count", 0) or 0)
            or int(local_meta.get("invalid_ohlc_rows", 0) or 0)
            or int(local_meta.get("non_monotonic_timestamps", 0) or 0)
        ):
            return "LOCAL_H4_CORRUPT_REBUILD_CANDIDATE"
        return "MT5_H4_SOURCE_MISMATCH_MANUAL_REVIEW"
    if match_rate == 1.0:
        return "NO_ACTION_DATA_OK"
    return "DO_NOT_RECOVER_UNSAFE"


def _write_candidate_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True).dt.strftime("%Y.%m.%d %H:%M")
    out.to_csv(path, index=False, encoding="utf-8")


def write_reports(summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "h4_data_source_diagnostic.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
    mismatch_rows = summary.get("overlap", {}).get("mismatch_examples", [])
    if mismatch_rows:
        pd.DataFrame(mismatch_rows).to_csv(output_dir / "h4_overlap_mismatches.csv", index=False, encoding="utf-8")
    else:
        pd.DataFrame(columns=["timestamp", "materiality"]).to_csv(output_dir / "h4_overlap_mismatches.csv", index=False, encoding="utf-8")
    lines = [
        "# Strategy 3 H4 Data Source Diagnostic",
        "",
        "This is a dry data-source diagnostic unless `--apply-rebuild` is explicitly passed. No live trading, Telegram, broker execution, or Strategy 3 logic change is involved.",
        "",
        f"- symbol: `{summary.get('symbol')}`",
        f"- broker_symbol: `{summary.get('symbol_broker')}`",
        f"- recommendation: `{summary.get('recommendation')}`",
        f"- local_latest: `{summary.get('local_h4', {}).get('latest_timestamp')}`",
        f"- mt5_latest_closed: `{summary.get('mt5_h4', {}).get('latest_closed_timestamp')}`",
        f"- overlap_count: `{summary.get('overlap', {}).get('overlap_count')}`",
        f"- match_rate_ohlc: `{summary.get('overlap', {}).get('match_rate_ohlc')}`",
        f"- match_rate_ohlcv: `{summary.get('overlap', {}).get('match_rate_ohlcv')}`",
        f"- first_mismatch_timestamp: `{summary.get('overlap', {}).get('first_mismatch_timestamp')}`",
        f"- worst_ohlc_diff: `{summary.get('overlap', {}).get('worst_ohlc_diff')}`",
        f"- worst_ohlc_diff_timestamp: `{summary.get('overlap', {}).get('worst_ohlc_diff_timestamp')}`",
        f"- best_shift_by_match_rate: `{summary.get('timezone_boundary_diagnostics', {}).get('best_shift_by_match_rate')}`",
        f"- best_shift_match_rate: `{summary.get('timezone_boundary_diagnostics', {}).get('best_shift_match_rate')}`",
        f"- can_append_safely: `{summary.get('append_rebuild_diagnostic', {}).get('can_append_safely')}`",
        f"- rebuild_candidate_created: `{summary.get('append_rebuild_diagnostic', {}).get('rebuild_candidate_created')}`",
        f"- data_h4_modified: `{summary.get('data_h4_modified')}`",
        f"- backup_created: `{summary.get('backup_created')}`",
        "",
        "## Candidate Files",
        "",
    ]
    for path in summary.get("candidate_files", []):
        lines.append(f"- `{path}`")
    lines.extend(["", "## Safety", "", "- no live", "- no Telegram", "- no orders", "- no broker execution", "- no Strategy 3/VWAP/sigma/cooldown changes", ""])
    (output_dir / "h4_data_source_diagnostic.md").write_text("\n".join(lines), encoding="utf-8")


def maybe_write_candidates(cfg: H4DiagnosticConfig, local: pd.DataFrame, mt5: pd.DataFrame, summary: dict[str, Any]) -> list[str]:
    if not cfg.candidate_rebuild_output:
        return []
    paths: list[str] = []
    if not mt5.empty:
        candidate = cfg.output_dir / "h4_mt5_candidate.csv"
        _write_candidate_csv(mt5, candidate)
        paths.append(str(candidate))
    local_latest = _latest_timestamp(local)
    if local_latest is not None and not mt5.empty:
        append = mt5[pd.to_datetime(mt5["time"], utc=True) > local_latest].copy()
        if not append.empty:
            append_path = cfg.output_dir / "h4_append_candidate.csv"
            _write_candidate_csv(append, append_path)
            paths.append(str(append_path))
    recommendation = summary.get("recommendation")
    if recommendation == "LOCAL_H4_CORRUPT_REBUILD_CANDIDATE" and not mt5.empty:
        rebuild_path = cfg.output_dir / "h4_rebuild_candidate.csv"
        _write_candidate_csv(mt5, rebuild_path)
        paths.append(str(rebuild_path))
    return paths


def maybe_apply_rebuild(cfg: H4DiagnosticConfig, local: pd.DataFrame, mt5: pd.DataFrame, schema: list[str], timestamp_has_time: bool, summary: dict[str, Any]) -> dict[str, Any]:
    if not cfg.apply_rebuild:
        return {"data_h4_modified": False, "backup_created": False, "backup_path": None}
    if cfg.dry_run:
        return {
            "data_h4_modified": False,
            "backup_created": False,
            "backup_path": None,
            "apply_rebuild_block_reason": "dry_run_enabled",
        }
    recommendation = summary.get("recommendation")
    if recommendation not in {"LOCAL_H4_STALE_APPEND_SAFE", "LOCAL_H4_CORRUPT_REBUILD_CANDIDATE"}:
        return {
            "data_h4_modified": False,
            "backup_created": False,
            "backup_path": None,
            "apply_rebuild_block_reason": f"recommendation_not_apply_safe:{recommendation}",
        }
    h4_path = cfg.data_dir / cfg.symbol / "H4.csv"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = h4_path.with_name(f"{h4_path.name}.backup.{stamp}")
    shutil.copy2(h4_path, backup)
    if recommendation == "LOCAL_H4_STALE_APPEND_SAFE":
        local_latest = _latest_timestamp(local)
        missing = mt5[pd.to_datetime(mt5["time"], utc=True) > local_latest].copy()
        merged = pd.concat([local, missing], ignore_index=True, sort=False).drop_duplicates(subset=["time"], keep="first").sort_values("time")
    else:
        merged = mt5.copy()
    write_project_csv(merged, h4_path, schema, timestamp_has_time=timestamp_has_time)
    return {"data_h4_modified": True, "backup_created": True, "backup_path": str(backup)}


def build_diagnostic(cfg: H4DiagnosticConfig, *, mt5_module: Any | None = None, now_utc: datetime | None = None) -> dict[str, Any]:
    started = perf_counter()
    run_started_at = datetime.now(timezone.utc).isoformat()
    now = now_utc or datetime.now(timezone.utc)
    local, local_meta, schema, timestamp_has_time = load_local_h4(cfg.data_dir, cfg.symbol)
    expected = expected_latest_closed_timestamp(now, "H4", cfg.closed_candle_grace_seconds)
    local_latest = _latest_timestamp(local)
    stale_seconds = float((expected - local_latest).total_seconds()) if local_latest is not None and local_latest < expected else 0.0
    local_meta["latest_closed_expected_timestamp"] = _iso(expected)
    local_meta["stale_by_seconds"] = stale_seconds
    local_meta["stale_by_bars"] = int(stale_seconds // (4 * 3600)) if stale_seconds > 0 else 0

    mt5_frame, mt5_meta = fetch_mt5_h4(
        symbol_broker=cfg.symbol_broker,
        lookback_bars=cfg.lookback_bars,
        include_forming_candles=cfg.include_forming_candles,
        closed_candle_grace_seconds=cfg.closed_candle_grace_seconds,
        mt5_module=mt5_module,
        now_utc=now,
    )
    comparison = compare_h4_frames(local, mt5_frame, cfg.price_tolerance_usd)
    timezone_diag = timezone_shift_diagnostic(local, mt5_frame, cfg.price_tolerance_usd)
    append_diag = append_rebuild_diagnostic(local, mt5_frame, comparison)
    recommendation = classify_recommendation(
        local_meta=local_meta,
        mt5_meta=mt5_meta,
        comparison=comparison,
        timezone_diag=timezone_diag,
        append_diag=append_diag,
    )
    summary: dict[str, Any] = {
        "run_started_at": run_started_at,
        "symbol": cfg.symbol,
        "symbol_broker": cfg.symbol_broker,
        "data_dir": str(cfg.data_dir),
        "output_dir": str(cfg.output_dir),
        "lookback_bars": cfg.lookback_bars,
        "dry_run": cfg.dry_run,
        "include_forming_candles": cfg.include_forming_candles,
        "closed_candle_grace_seconds": cfg.closed_candle_grace_seconds,
        "local_h4": local_meta,
        "mt5_h4": mt5_meta,
        "overlap": comparison,
        "timezone_boundary_diagnostics": timezone_diag,
        "append_rebuild_diagnostic": append_diag,
        "recommendation": recommendation,
        "candidate_files": [],
        "data_h4_modified": False,
        "backup_created": False,
        "backup_path": None,
        "scanner_should_remain_blocked": recommendation not in {"NO_ACTION_DATA_OK", "LOCAL_H4_STALE_APPEND_SAFE"} or not cfg.apply_rebuild,
        "paper_signals_clean_for_validation": False,
        "safety": dict(SAFETY),
    }
    summary["candidate_files"] = maybe_write_candidates(cfg, local, mt5_frame, summary)
    summary["append_rebuild_diagnostic"]["rebuild_candidate_created"] = any(path.endswith("h4_rebuild_candidate.csv") for path in summary["candidate_files"])
    summary["append_rebuild_diagnostic"]["append_candidate_created"] = any(path.endswith("h4_append_candidate.csv") for path in summary["candidate_files"])
    apply_result = maybe_apply_rebuild(cfg, local, mt5_frame, schema, timestamp_has_time, summary)
    summary.update(apply_result)
    summary["run_finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["runtime_seconds"] = round(perf_counter() - started, 4)
    write_reports(summary, cfg.output_dir)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = H4DiagnosticConfig(
        symbol=args.symbol,
        symbol_broker=args.symbol_broker or args.symbol,
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        lookback_bars=int(args.lookback_bars),
        dry_run=bool(args.dry_run or not args.apply_rebuild),
        include_forming_candles=bool(args.include_forming_candles),
        closed_candle_grace_seconds=int(args.closed_candle_grace_seconds),
        candidate_rebuild_output=bool(args.candidate_rebuild_output),
        apply_rebuild=bool(args.apply_rebuild),
    )
    summary = build_diagnostic(cfg)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
