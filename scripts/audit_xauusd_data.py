from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dazro_trade.backtest.data_loader import _coerce_utc, _read_csv_robust

SUPPORTED_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]
TIMEFRAME_INTERVALS = {
    "M1": pd.Timedelta(minutes=1),
    "M5": pd.Timedelta(minutes=5),
    "M15": pd.Timedelta(minutes=15),
    "H1": pd.Timedelta(hours=1),
    "H4": pd.Timedelta(hours=4),
    "D1": pd.Timedelta(days=1),
}
BROKER_COLUMN_ALIASES = {
    "datetime": "time",
    "timestamp": "time",
    "date": "time",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "tick_volume",
    "tickvolume": "tick_volume",
    "tick_volume": "tick_volume",
    "vol": "tick_volume",
    "spread": "spread",
    "spr": "spread",
}
CANONICAL_SCHEMA = ["time", "open", "high", "low", "close", "tick_volume", "spread"]


@dataclass(frozen=True)
class FrameReadResult:
    frame: pd.DataFrame
    schema: list[str]
    timestamp_has_time: bool
    encoding: str | None
    separator: str | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit local XAUUSD candle CSVs")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframes", default=",".join(SUPPORTED_TIMEFRAMES))
    parser.add_argument("--output-dir", default="backtests/reports/strategy_3_data_ingestion")
    return parser.parse_args(argv)


def _split_timeframes(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip().strip("<>").lower().replace(" ", "_") for c in out.columns]
    if "date" in out.columns and "time" in out.columns:
        out["time"] = out["date"].astype(str).str.strip() + " " + out["time"].astype(str).str.strip()
        out = out.drop(columns=["date"])
    rename: dict[str, str] = {}
    for column in out.columns:
        alias = BROKER_COLUMN_ALIASES.get(column)
        if alias and alias not in out.columns and alias not in rename.values():
            rename[column] = alias
    if rename:
        out = out.rename(columns=rename)
    drop_dupes = [c for c in ("vol", "tickvolume", "volume", "spr") if c in out.columns and c not in CANONICAL_SCHEMA]
    if drop_dupes:
        out = out.drop(columns=drop_dupes)
    return out


def read_candle_csv(path: Path) -> FrameReadResult:
    raw = _read_csv_robust(path)
    encoding = raw.attrs.get("source_encoding")
    separator = raw.attrs.get("source_separator")
    df = _normalize_columns(raw)
    original_time = df["time"].astype(str) if "time" in df.columns else pd.Series(dtype=str)
    timestamp_has_time = bool(original_time.str.contains(":", regex=False).any()) if len(original_time) else True
    if "time" in df.columns:
        df["time"] = _coerce_utc(df["time"])
    for col in ("open", "high", "low", "close", "tick_volume", "spread"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    schema = [col for col in df.columns]
    return FrameReadResult(frame=df, schema=schema, timestamp_has_time=timestamp_has_time, encoding=encoding, separator=separator)


def validate_frame(df: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rows": int(len(df)),
        "duplicate_timestamps": 0,
        "non_monotonic_timestamps": 0,
        "gaps": 0,
        "missing_ohlc_values": 0,
        "invalid_ohlc_rows": 0,
        "parseable_timestamps": 0,
    }
    if df.empty or "time" not in df.columns:
        return result
    times = pd.to_datetime(df["time"], utc=True, errors="coerce")
    result["parseable_timestamps"] = int(times.notna().sum())
    result["first_timestamp"] = times.min().isoformat() if times.notna().any() else None
    result["last_timestamp"] = times.max().isoformat() if times.notna().any() else None
    result["duplicate_timestamps"] = int(times.duplicated(keep=False).sum())
    diffs = times.diff().dropna()
    result["non_monotonic_timestamps"] = int((diffs <= pd.Timedelta(0)).sum())
    interval = TIMEFRAME_INTERVALS.get(timeframe)
    if interval is not None:
        result["gaps"] = int((diffs > interval).sum())
        max_gap = diffs.max() if len(diffs) else pd.NaT
        result["max_gap_seconds"] = float(max_gap.total_seconds()) if pd.notna(max_gap) else 0.0
    ohlc = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if ohlc:
        result["missing_ohlc_values"] = int(df[ohlc].isna().any(axis=1).sum())
    if {"open", "high", "low", "close"}.issubset(df.columns):
        invalid = (
            (df["high"] < df["low"])
            | (df["open"] > df["high"])
            | (df["open"] < df["low"])
            | (df["close"] > df["high"])
            | (df["close"] < df["low"])
        )
        result["invalid_ohlc_rows"] = int(invalid.fillna(False).sum())
    return result


def audit_timeframe(data_dir: Path, symbol: str, timeframe: str) -> dict[str, Any]:
    path = data_dir / symbol / f"{timeframe}.csv"
    item: dict[str, Any] = {"timeframe": timeframe, "path": str(path), "exists": path.exists()}
    if not path.exists():
        item["verdict_flags"] = ["FILE_MISSING"]
        return item
    try:
        read = read_candle_csv(path)
        validation = validate_frame(read.frame, timeframe)
        item.update(validation)
        item["schema"] = read.schema
        item["encoding"] = read.encoding
        item["separator"] = read.separator
        item["timestamp_has_time"] = read.timestamp_has_time
    except Exception as exc:
        item["error"] = str(exc)
        item["verdict_flags"] = ["DATA_AUDIT_FAILED"]
        return item
    flags: list[str] = []
    if item.get("duplicate_timestamps", 0):
        flags.append("DUPLICATE_TIMESTAMPS_DETECTED")
    if item.get("non_monotonic_timestamps", 0):
        flags.append("NON_MONOTONIC_TIMESTAMPS_DETECTED")
    if item.get("gaps", 0):
        flags.append("GAPS_DETECTED")
    if item.get("invalid_ohlc_rows", 0):
        flags.append("INVALID_OHLC_DETECTED")
    if item.get("missing_ohlc_values", 0):
        flags.append("MISSING_OHLC_VALUES_DETECTED")
    item["verdict_flags"] = flags
    return item


def build_audit(data_dir: Path, symbol: str, timeframes: list[str]) -> dict[str, Any]:
    frames = [audit_timeframe(data_dir, symbol, tf) for tf in timeframes]
    firsts = [pd.Timestamp(item["first_timestamp"]) for item in frames if item.get("first_timestamp")]
    lasts = [pd.Timestamp(item["last_timestamp"]) for item in frames if item.get("last_timestamp")]
    all_flags = sorted({flag for item in frames for flag in item.get("verdict_flags", [])})
    status = "DATA_AUDIT_OK"
    if any(flag in all_flags for flag in ("FILE_MISSING", "DATA_AUDIT_FAILED", "INVALID_OHLC_DETECTED", "NON_MONOTONIC_TIMESTAMPS_DETECTED")):
        status = "DATA_AUDIT_FAILED"
    elif all_flags:
        status = "DATA_AUDIT_WARNINGS"
    return {
        "symbol": symbol,
        "timeframes": frames,
        "earliest_common_timestamp": max(firsts).isoformat() if firsts else None,
        "latest_common_timestamp": min(lasts).isoformat() if lasts else None,
        "verdict_flags": [status] + all_flags,
        "safety": {
            "data_modified": False,
            "live_trading_enabled": False,
            "telegram_enabled": False,
            "order_execution_enabled": False,
            "broker_called": False,
            "telegram_sent": False,
            "order_sent": False,
        },
    }


def write_audit_report(audit: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit_summary.json").write_text(json.dumps(audit, indent=2, sort_keys=True, default=str), encoding="utf-8")
    lines = [
        "# XAUUSD Data Audit",
        "",
        f"- symbol: `{audit['symbol']}`",
        f"- earliest_common_timestamp: `{audit['earliest_common_timestamp']}`",
        f"- latest_common_timestamp: `{audit['latest_common_timestamp']}`",
        f"- verdict_flags: `{', '.join(audit['verdict_flags'])}`",
        "",
        "| TF | rows | first | last | duplicates | non_monotonic | gaps | invalid_ohlc | missing_ohlc |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in audit["timeframes"]:
        lines.append(
            f"| {item['timeframe']} | {item.get('rows', 0)} | {item.get('first_timestamp')} | {item.get('last_timestamp')} | "
            f"{item.get('duplicate_timestamps', 0)} | {item.get('non_monotonic_timestamps', 0)} | {item.get('gaps', 0)} | "
            f"{item.get('invalid_ohlc_rows', 0)} | {item.get('missing_ohlc_values', 0)} |"
        )
    lines.extend(["", "This audit is read-only and does not modify source data.", ""])
    (output_dir / "audit_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = perf_counter()
    audit = build_audit(Path(args.data_dir), args.symbol, _split_timeframes(args.timeframes))
    audit["runtime_seconds"] = round(perf_counter() - started, 4)
    audit["output_dir"] = args.output_dir
    write_audit_report(audit, Path(args.output_dir))
    print(json.dumps(audit, indent=2, sort_keys=True, default=str))
    return 0 if "DATA_AUDIT_FAILED" not in audit["verdict_flags"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
